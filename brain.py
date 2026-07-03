#!/usr/bin/env python3
"""Meeting assistant — the periodic 'brain'.

Runs every 60s under launchd (StartInterval, no KeepAlive). Each run is a fresh,
short-lived process: it reads the cached Google Calendar feed, figures out which
meetings are approaching, and fires the right channels (voice, full-screen
overlay, auto-open link). It then exits. launchd is the watchdog — a crash just
means next minute's run is healthy. See README for the design rationale.

Responsibilities of THIS process: decisions + voice + auto-open + health checks.
Persistence + live countdown live in the detached Swift overlay it launches.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import logging
import os
import re
import signal
import subprocess
import sys
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler
from pathlib import Path
from zoneinfo import ZoneInfo

import recurring_ical_events
import requests
from icalendar import Calendar

BASE = Path.home() / ".meeting-assistant"
CACHE = BASE / "cache"
RUNTIME = BASE / "runtime"
LOGS = BASE / "logs"
BIN = BASE / "bin"
URL_FILE = BASE / "calendar-url.txt"   # legacy secret location (still honoured)
ENV_FILE = BASE / ".env"
STATE_FILE = BASE / "state.json"
CONFIG_FILE = BASE / "config.json"
LOCK_FILE = BASE / "runtime" / "tick.lock"
STOP_FILE = BASE / "stopped"   # presence = hard off switch; brain no-ops while it exists

DEFAULT_CONFIG = {
    "timezone": "Asia/Kolkata",
    "name": "there",                  # your name (set in config.json)
    "assistant_name": "Tara",         # what she calls herself
    "name_frequency": 0.4,            # how often she uses your name (0..1)
    "my_email": "",                   # your email — set in config.json to read RSVP status
    "rsvp": {                         # behaviour per response status:
        "accepted": "full",          #   full   = lead + overlay + auto-open + escalating nag
        "needs_action": "remind",    #   remind = lead + overlay, no auto-open, no nagging
        "tentative": "remind",       #   skip   = ignore entirely
        "declined": "skip",
    },
    "tts": {
        "engine": "edge",             # edge (neural, human) | say (offline, robotic)
        "edge_voice": "en-IN-NeerjaExpressiveNeural",
        "edge_rate": "-3%",
        "say_voice": "Tara",          # offline fallback voice
        "say_rate": 175,
    },
    "lead_times_min": [5, 2],         # spoken pre-alerts
    "overlay_lead_min": 3,            # full-screen overlay appears this early
    "voice_gap_sec": 1.5,             # silence between queued announcements
    "overdue_nag_minutes": 12,        # keep nagging this long past start, then give up
    "fetch_interval_sec": 300,        # re-download the feed at most this often
    "index_window_hours": 36,         # how far ahead to pre-expand events
    "index_rebuild_hours": 6,         # rebuild index at least this often
    "stale_alert_after_min": 60,      # fail-loud if no good fetch for this long
    "stale_realert_every_min": 30,
    "work_hours": {"start": "08:00", "end": "21:00"},
    "briefing_time": "07:30",         # morning agenda read-out
    "snooze_min": 2,
    "overlay_theme": "midnight",      # midnight | sunrise | forest | grape | mono
    "lunch": {
        "enabled": True,
        "earliest": "12:30",          # don't nudge before this
        "latest": "14:00",            # must have eaten by here
        "min_minutes": 20,            # smallest gap worth calling "lunch"
    },
    "wrap_up": {
        "enabled": True,
        "lead_min": 5,                # warn this long before the current meeting ends
        "next_within_min": 15,        # ...but only if the next one starts this soon after
    },
}

log = logging.getLogger("brain")


# --------------------------------------------------------------------------- #
# infrastructure
# --------------------------------------------------------------------------- #
def setup_logging() -> None:
    LOGS.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(LOGS / "assistant.log", maxBytes=1_000_000, backupCount=3)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(handler)
    log.setLevel(logging.INFO)


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_FILE.exists():
        try:
            cfg.update(json.loads(CONFIG_FILE.read_text()))
        except Exception as exc:  # noqa: BLE001
            log.warning("bad config.json, using defaults: %s", exc)
    return cfg


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:  # noqa: BLE001
            log.warning("unreadable state.json, starting fresh")
    return {}


def save_state(state: dict) -> None:
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2, default=str))
    tmp.replace(STATE_FILE)


def acquire_lock():
    """Prevent overlapping ticks (the classic periodic-job pitfall)."""
    RUNTIME.mkdir(parents=True, exist_ok=True)
    fh = open(LOCK_FILE, "w")
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        log.info("previous tick still running; skipping")
        sys.exit(0)
    return fh  # keep handle alive for process lifetime


# --------------------------------------------------------------------------- #
# output channels
# --------------------------------------------------------------------------- #
VOICE_WORKER = BASE / "voice.py"


def speak(text: str, cfg: dict) -> None:
    """Speak in the assistant's voice, non-blocking. Each utterance is handed to
    a detached voice.py worker; workers synthesize in parallel (edge-tts, with a
    macOS `say` fallback so a reminder is NEVER lost to a network blip) but
    serialize PLAYBACK through a queue with a short gap between lines — two
    announcements landing on the same tick used to talk over each other."""
    log.info("speak: %s", text)
    try:
        subprocess.Popen([sys.executable, str(VOICE_WORKER), text],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
    except Exception as exc:  # noqa: BLE001
        log.error("speak failed: %s", exc)


_PHRASES: dict | None = None


def pick(category: str, cfg: dict, **kw) -> str:
    """Return a randomly chosen phrase for the category, formatted with kw.
    Keeps the assistant from saying the exact same line every day."""
    import random
    global _PHRASES
    if _PHRASES is None:
        try:
            _PHRASES = json.loads((BASE / "phrases.json").read_text())
        except Exception:  # noqa: BLE001
            _PHRASES = {}
    kw.setdefault("name", cfg.get("name", "there"))
    kw.setdefault("assistant", cfg.get("assistant_name", "Tara"))
    options = _PHRASES.get(category) or ["{title}" if "title" in kw else ""]
    template = random.choice(options)
    # When she's annoyed, ALWAYS use the name. Otherwise use it only "every now and
    # then" — if a name line was picked but we're over budget, prefer a no-name one.
    always_name = category in ("overdue_firm", "overdue_upset", "briefing_greeting",
                               "overlay_line_late")
    if "{name}" in template and not always_name and random.random() > cfg.get("name_frequency", 0.4):
        alts = [o for o in options if "{name}" not in o]
        if alts:
            template = random.choice(alts)
    try:
        return template.format(**kw)
    except Exception:  # noqa: BLE001 (missing placeholder — return raw)
        return template


def open_url(url: str) -> None:
    if not url:
        return
    try:
        subprocess.Popen(["/usr/bin/open", url],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        log.info("opened meeting link")
    except Exception as exc:  # noqa: BLE001
        log.error("open failed: %s", exc)


def launch_overlay(safe_id: str, title: str, start_iso: str, url: str,
                   mode: str = "meeting", theme: str = "midnight",
                   lead_min: float = 3, snooze_min: int = 2,
                   line: str = "", late_line: str = "") -> int | None:
    overlay = BIN / "overlay"
    if not overlay.exists():
        log.warning("overlay binary missing; voice-only")
        return None
    try:
        proc = subprocess.Popen(
            [str(overlay),
             "--id", safe_id, "--title", title, "--start", start_iso,
             "--url", url or "", "--mode", mode, "--theme", theme,
             "--runtime", str(RUNTIME),
             "--lead", str(lead_min), "--snooze", str(snooze_min),
             "--line", line, "--lateline", late_line],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,   # detach: survives this tick exiting
        )
        log.info("launched overlay pid=%s mode=%s", proc.pid, mode)
        return proc.pid
    except Exception as exc:  # noqa: BLE001
        log.error("overlay launch failed: %s", exc)
        return None


def pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def kill_overlay(pid: int | None) -> None:
    if pid_alive(pid):
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            pass


# --------------------------------------------------------------------------- #
# join detection
# --------------------------------------------------------------------------- #
def mic_in_use() -> bool:
    """Universal 'in a call' signal — covers Zoom, Meet (Brave PWA / Arc), Teams."""
    miccheck = BIN / "miccheck"
    if miccheck.exists():
        try:
            out = subprocess.run([str(miccheck)], capture_output=True, text=True, timeout=5)
            return out.stdout.strip() == "1"
        except Exception:  # noqa: BLE001
            pass
    return False


def cam_in_use() -> bool:
    """Camera-active signal (CoreMediaIO). A strong 'really here' cue when Sujit
    turns video on — but he doesn't always, so it only ever strengthens, never
    gates, join detection."""
    camcheck = BIN / "camcheck"
    if camcheck.exists():
        try:
            out = subprocess.run([str(camcheck)], capture_output=True, text=True, timeout=5)
            return out.stdout.strip() == "1"
        except Exception:  # noqa: BLE001
            pass
    return False


def zoom_in_meeting() -> bool:
    try:
        out = subprocess.run(["/usr/bin/pgrep", "-x", "CptHost"],
                             capture_output=True, text=True, timeout=5)
        return out.returncode == 0
    except Exception:  # noqa: BLE001
        return False


def joined_for(ev_start, now, *, mic_active, mic_on_since, zoom_live, max_lead,
               cam_active=False, cam_on_since=None):
    """True only if Sujit has actually joined THIS meeting.

    Zoom's in-call helper (CptHost) is a hard yes. Mic and camera are weaker
    signals: each counts only if the device went live *recently* — within
    ~max_lead+2 min of the start. A device held open for hours by a background app
    (a Slack huddle, OBS, a VM, a stray Meet tab) is NOT a join; trusting it
    silently stood every meeting down, the exact silent-failure mode this app
    exists to kill. Camera is a strong "really here" cue when he turns video on,
    but he doesn't always — so it's an OR with the mic, never required. `now` is
    accepted for symmetry/future use though the test is start-relative.
    """
    if zoom_live:
        return True

    def recent(active, on_since):
        return bool(active and on_since
                    and on_since > ev_start - timedelta(minutes=max_lead + 2))

    return recent(mic_active, mic_on_since) or recent(cam_active, cam_on_since)


# --------------------------------------------------------------------------- #
# calendar
# --------------------------------------------------------------------------- #
LINK_PATTERNS = [
    r"https://meet\.google\.com/[a-z0-9\-]+",
    r"https://[\w.\-]*zoom\.us/(?:j|my|s|w)/[^\s>\"]+",
    r"https://teams\.microsoft\.com/[^\s>\"]+",
    r"https://teams\.live\.com/[^\s>\"]+",
]


def extract_link(ev) -> str:
    fields = []
    for key in ("X-GOOGLE-CONFERENCE", "LOCATION", "DESCRIPTION", "URL"):
        val = ev.get(key)
        if val:
            fields.append(str(val))
    blob = "\n".join(fields)
    for pat in LINK_PATTERNS:
        m = re.search(pat, blob)
        if m:
            return m.group(0).rstrip(".,)")
    # last resort: any http(s) link in location
    m = re.search(r"https?://[^\s>\"]+", str(ev.get("LOCATION") or ""))
    return m.group(0) if m else ""


def read_env(key: str) -> str | None:
    """Read a secret from a real env var, else from the .env file (KEY=VALUE)."""
    if os.environ.get(key):
        return os.environ[key].strip()
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            if k.strip() == key:
                return v.strip().strip('"').strip("'")
    return None


def read_calendar_url() -> str | None:
    """Calendar feed URL: .env (CALENDAR_ICAL_URL) first, then legacy file."""
    url = read_env("CALENDAR_ICAL_URL")
    if url:
        return url
    if URL_FILE.exists():
        return URL_FILE.read_text().strip()
    return None


def fetch_feed(state: dict, cfg: dict, tz: ZoneInfo) -> None:
    now = datetime.now(tz)
    last_attempt = state.get("last_fetch_attempt")
    if last_attempt:
        if (now - datetime.fromisoformat(last_attempt)).total_seconds() < cfg["fetch_interval_sec"]:
            return  # not due yet; per-minute ticks read the cache
    state["last_fetch_attempt"] = now.isoformat()
    url = read_calendar_url()
    if not url:
        log.error("no calendar URL configured (.env CALENDAR_ICAL_URL)")
        return
    headers = {}
    if state.get("etag"):
        headers["If-None-Match"] = state["etag"]
    if state.get("last_modified"):
        headers["If-Modified-Since"] = state["last_modified"]
    try:
        resp = requests.get(url, headers=headers, timeout=20)
    except Exception as exc:  # noqa: BLE001
        log.error("feed fetch error (network): %s", type(exc).__name__)
        return
    if resp.status_code == 304:
        state["last_good_fetch"] = now.isoformat()  # cache confirmed current
        return
    if resp.status_code != 200:
        log.error("feed fetch HTTP %s", resp.status_code)
        return
    CACHE.mkdir(parents=True, exist_ok=True)
    (CACHE / "last.ics").write_bytes(resp.content)
    state["etag"] = resp.headers.get("ETag")
    state["last_modified"] = resp.headers.get("Last-Modified")
    state["last_good_fetch"] = now.isoformat()
    state["_feed_changed"] = True  # triggers an index rebuild this tick
    log.info("feed refreshed (%d bytes)", len(resp.content))


INDEX_FILE = BASE / "events.json"


def my_partstat(ev, my_email: str) -> str:
    """My RSVP status for this event. Default ACCEPTED when I'm not listed as an
    attendee (i.e. I organise it or it's a solo block)."""
    att = ev.get("ATTENDEE")
    if not att or not my_email:
        return "ACCEPTED"
    atts = att if isinstance(att, list) else [att]
    for a in atts:
        if my_email in str(a).lower():
            return str(a.params.get("PARTSTAT", "NEEDS-ACTION")).upper()
    return "ACCEPTED"


def build_event_index(cfg: dict, tz: ZoneInfo) -> bool:
    """Expensive step (~4s on a 12MB feed): parse + expand recurrences ONCE and
    cache a tiny list, so per-minute ticks stay near-instant."""
    ics = CACHE / "last.ics"
    if not ics.exists():
        return False
    cal = Calendar.from_ical(ics.read_bytes())
    now = datetime.now(tz)
    my_email = cfg.get("my_email", "").lower()
    win_start = now - timedelta(hours=2)
    win_end = now + timedelta(hours=cfg["index_window_hours"])
    out = []
    for ev in recurring_ical_events.of(cal).between(win_start, win_end):
        dt = ev.get("DTSTART").dt
        if not isinstance(dt, datetime):
            continue  # all-day event — skip (we want timed events)
        start = dt.astimezone(tz) if dt.tzinfo else dt.replace(tzinfo=tz)
        end_prop = ev.get("DTEND")
        if end_prop is not None and isinstance(end_prop.dt, datetime):
            ed = end_prop.dt
            end = ed.astimezone(tz) if ed.tzinfo else ed.replace(tzinfo=tz)
        else:
            end = start + timedelta(minutes=30)
        uid = str(ev.get("UID", ""))
        recurring = bool(ev.get("RRULE") or ev.get("RDATE") or ev.get("RECURRENCE-ID"))
        out.append({
            "key": f"{uid}@{start.isoformat()}",
            "title": str(ev.get("SUMMARY", "Untitled meeting")),
            "start": start.isoformat(),
            "end": end.isoformat(),
            "url": extract_link(ev),
            "recurring": recurring,
            "partstat": my_partstat(ev, my_email),
        })
    INDEX_FILE.write_text(json.dumps({"built": now.isoformat(), "events": out}, default=str))
    log.info("event index rebuilt: %d timed events", len(out))
    return True


def index_age_hours(tz: ZoneInfo) -> float | None:
    if not INDEX_FILE.exists():
        return None
    built = json.loads(INDEX_FILE.read_text())["built"]
    return (datetime.now(tz) - datetime.fromisoformat(built)).total_seconds() / 3600


def load_events(cfg: dict, tz: ZoneInfo, feed_changed: bool) -> list[dict]:
    age = index_age_hours(tz)
    if feed_changed or age is None or age > cfg["index_rebuild_hours"]:
        build_event_index(cfg, tz)
    if not INDEX_FILE.exists():
        return []
    data = json.loads(INDEX_FILE.read_text())
    out = []
    for e in data["events"]:
        out.append({
            "key": e["key"], "title": e["title"],
            "start": datetime.fromisoformat(e["start"]),
            "end": datetime.fromisoformat(e["end"]) if e.get("end")
                   else datetime.fromisoformat(e["start"]) + timedelta(minutes=30),
            "url": e["url"],
            "recurring": e.get("recurring", False),
            "partstat": e.get("partstat", "ACCEPTED"),
        })
    return out


def alert_level(ev: dict, cfg: dict) -> str:
    """Map my RSVP status to behaviour: 'full' | 'remind' | 'skip'."""
    key = {"ACCEPTED": "accepted", "NEEDS-ACTION": "needs_action",
           "TENTATIVE": "tentative", "DECLINED": "declined"}.get(ev["partstat"], "accepted")
    return cfg.get("rsvp", {}).get(key, "full")


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def safe_id(key: str) -> str:
    return hashlib.md5(key.encode()).hexdigest()[:16]


def within_work_hours(now: datetime, cfg: dict) -> bool:
    s = datetime.strptime(cfg["work_hours"]["start"], "%H:%M").time()
    e = datetime.strptime(cfg["work_hours"]["end"], "%H:%M").time()
    return s <= now.time() <= e


def read_choice(sid: str) -> str | None:
    f = RUNTIME / f"{sid}.choice"
    if f.exists():
        val = f.read_text().strip()
        f.unlink(missing_ok=True)
        return val
    return None


def fmt_time(dt: datetime) -> str:
    return dt.strftime("%-I:%M %p").lower()


# --------------------------------------------------------------------------- #
# fail-loud
# --------------------------------------------------------------------------- #
def fail_loud_check(state: dict, cfg: dict, tz: ZoneInfo) -> None:
    now = datetime.now(tz)
    last_good = state.get("last_good_fetch")
    never = last_good is None and not (CACHE / "last.ics").exists()
    stale = False
    if last_good:
        age_min = (now - datetime.fromisoformat(last_good)).total_seconds() / 60
        stale = age_min > cfg["stale_alert_after_min"]
    if not (never or stale):
        return
    if not within_work_hours(now, cfg):
        return
    last_alert = state.get("last_stale_alert")
    if last_alert:
        if (now - datetime.fromisoformat(last_alert)).total_seconds() / 60 < cfg["stale_realert_every_min"]:
            return
    msg = pick("calendar_error_never", cfg) if never else pick("calendar_error", cfg)
    log.error("FAIL-LOUD: calendar unreachable (never=%s)", never)
    speak(msg, cfg)
    launch_overlay("calendar-error", "⚠️ Calendar unreachable",
                   now.isoformat(), "", mode="error")
    state["last_stale_alert"] = now.isoformat()


# --------------------------------------------------------------------------- #
# briefing
# --------------------------------------------------------------------------- #
def maybe_briefing(events: list[dict], state: dict, cfg: dict, tz: ZoneInfo) -> None:
    now = datetime.now(tz)
    bt = datetime.strptime(cfg["briefing_time"], "%H:%M").time()
    today = now.date().isoformat()
    if state.get("last_briefing_date") == today:
        return
    # fire within a 30-min window after briefing_time (in case Mac was asleep)
    target = now.replace(hour=bt.hour, minute=bt.minute, second=0, microsecond=0)
    if not (target <= now <= target + timedelta(minutes=30)):
        return
    state["last_briefing_date"] = today
    speak_briefing(events, cfg, tz)


def speak_briefing(events: list[dict], cfg: dict, tz: ZoneInfo) -> None:
    now = datetime.now(tz)
    today = sorted([e for e in events
                    if e["start"] >= now and e["start"].date() == now.date()
                    and e["partstat"] != "DECLINED"],  # don't brief on declined
                   key=lambda e: e["start"])
    greeting = pick("briefing_greeting", cfg)  # good morning + beautiful-day spirit
    if not today:
        speak(" ".join([greeting, pick("briefing_no_meetings", cfg),
                        pick("briefing_close", cfg)]), cfg)
        return
    oneoffs = [e for e in today if not e["recurring"]]
    regulars = [e for e in today if e["recurring"]]
    n = len(today)
    parts = [greeting, pick("briefing_open", cfg, n=n, meetings="meeting" if n == 1 else "meetings")]
    # one-off meetings first — these are the ones you forget
    if oneoffs:
        k = "one meeting" if len(oneoffs) == 1 else f"{len(oneoffs)} meetings"
        parts.append(pick("briefing_oneoff_intro", cfg, k=k))
        for e in oneoffs:
            parts.append(pick("meeting_item", cfg, time=fmt_time(e["start"]), title=e["title"]))
    if regulars:
        if oneoffs:
            parts.append(pick("briefing_regular_intro", cfg))
        for e in regulars:
            parts.append(pick("meeting_item", cfg, time=fmt_time(e["start"]), title=e["title"]))
    # nudge about invites you still haven't responded to
    unresponded = [e for e in today if e["partstat"] == "NEEDS-ACTION"]
    if unresponded:
        parts.append(pick("briefing_unresponded", cfg))
    parts.append(pick("briefing_close", cfg))  # sign-off so you know she's done
    speak(" ".join(p for p in parts if p), cfg)
    log.info("briefing read: %d meetings (%d one-off, %d unresponded)",
             n, len(oneoffs), len(unresponded))


def maybe_lunch(events: list[dict], state: dict, cfg: dict, tz: ZoneInfo) -> None:
    """Nudge to lunch at the last good gap before afternoon meetings encroach.

    Waits until you're actually free, then if there's a >= min_minutes gap before
    your next meeting, says 'lunch now, you're free until X'. Example: meetings
    until 1:30 and the next at 2:00 -> fires at 1:30 ('free until your 2 PM').
    If meetings are back-to-back through the window, warns once at the latest time.
    """
    lc = cfg.get("lunch", {})
    if not lc.get("enabled", True):
        return
    now = datetime.now(tz)
    today = now.date().isoformat()
    if state.get("last_lunch_date") == today:
        return
    earliest = _today_at(now, lc.get("earliest", "12:30"))
    latest = _today_at(now, lc.get("latest", "14:00"))
    min_min = lc.get("min_minutes", 20)
    if now < earliest or now > latest:
        return

    todays = sorted([e for e in events if e["start"].date() == now.date()],
                    key=lambda e: e["start"])
    in_meeting = any(e["start"] <= now < e["end"] for e in todays)
    next_meeting = next((e for e in todays if e["start"] > now), None)

    if not in_meeting:
        # how long am I free starting now?
        gap_end = min(next_meeting["start"], latest + timedelta(hours=1)) if next_meeting else latest + timedelta(hours=1)
        free_min = (gap_end - now).total_seconds() / 60
        if free_min >= min_min:
            state["last_lunch_date"] = today
            if next_meeting and next_meeting["start"] <= latest + timedelta(hours=1):
                speak(pick("lunch_free", cfg, time=fmt_time(next_meeting["start"]),
                           title=next_meeting["title"]), cfg)
            else:
                speak(pick("lunch_clear", cfg), cfg)
            log.info("lunch nudge fired (free window)")
            return

    # back-to-back through the whole window: at the latest time, insist once
    if now >= latest - timedelta(minutes=1):
        state["last_lunch_date"] = today
        speak(pick("lunch_backtoback", cfg), cfg)
        log.info("lunch nudge fired (back-to-back warning)")


def _today_at(now: datetime, hhmm: str) -> datetime:
    t = datetime.strptime(hhmm, "%H:%M").time()
    return now.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)


def maybe_wrapup(events: list[dict], state: dict, cfg: dict, now: datetime,
                 in_call: bool) -> None:
    """Voice-only courtesy near the end of the CURRENT meeting: 'about 5 minutes
    left, and <next> is at <time>'. The mirror image of the join nag — it keeps
    back-to-back days from cascading. Deliberately narrow so it never becomes
    noise: fires once per meeting, only for a meeting he's actually in (acked it,
    or a mic/camera/Zoom call is live right now), and only when ANOTHER meeting
    starts within next_within_min of this one ending — if nothing follows,
    overrunning is his call and Tara stays quiet."""
    wc = cfg.get("wrap_up", {})
    if not wc.get("enabled", True):
        return
    lead = wc.get("lead_min", 5)
    next_win = wc.get("next_within_min", 15)
    wrapped = state.setdefault("wrapup", {})
    for ev in events:
        if not (ev["start"] <= now < ev["end"]):
            continue  # not in this meeting right now
        if ev["key"] in wrapped or alert_level(ev, cfg) == "skip":
            continue
        mins_left = (ev["end"] - now).total_seconds() / 60
        if mins_left > lead + 0.5:
            continue
        if not (ev["key"] in state.get("acked", {}) or in_call):
            continue  # he never joined this one; a wrap-up would be noise
        nxt = min((e for e in events
                   if e["key"] != ev["key"] and e["start"] > now
                   and e["start"] <= ev["end"] + timedelta(minutes=next_win)
                   and alert_level(e, cfg) != "skip"),
                  key=lambda e: e["start"], default=None)
        if nxt is None:
            continue
        wrapped[ev["key"]] = now.isoformat()
        mins_phrase = "a minute" if mins_left < 1.5 else f"{int(round(mins_left))} minutes"
        speak(pick("wrap_up", cfg, mins=mins_phrase,
                   title=nxt["title"], time=fmt_time(nxt["start"])), cfg)
        log.info("wrap-up warning for %r (next: %r)", ev["title"], nxt["title"])


# --------------------------------------------------------------------------- #
# the tick
# --------------------------------------------------------------------------- #
def tick() -> None:
    # Hard off switch. While this marker exists Tara does nothing — no voice, no
    # overlay, no nag — and any overlay still on screen is dismissed. Survives
    # reboots (it's a file), so even if launchd relaunches us we stay quiet until
    # the user resumes (menu bar "Resume Tara", or `rm ~/.meeting-assistant/stopped`).
    if STOP_FILE.exists():
        state = load_state()
        for rec in state.get("overlay", {}).values():
            kill_overlay(rec.get("pid"))
        log.info("stopped (off switch present); standing down")
        return

    cfg = load_config()
    tz = ZoneInfo(cfg["timezone"])
    state = load_state()
    state.setdefault("fired", {})
    state.setdefault("overlay", {})
    state.setdefault("acked", {})
    state.setdefault("snooze", {})
    state.setdefault("opened", {})
    state.setdefault("wrapup", {})

    fetch_feed(state, cfg, tz)
    fail_loud_check(state, cfg, tz)
    events = load_events(cfg, tz, feed_changed=state.pop("_feed_changed", False))
    maybe_briefing(events, state, cfg, tz)
    maybe_lunch(events, state, cfg, tz)

    now = datetime.now(tz)
    lead_times = sorted(cfg["lead_times_min"], reverse=True)
    max_lead = lead_times[0] if lead_times else 5

    # --- device tracking for rising-edge join detection -------------------- #
    # The mic/camera "is running" flags are unreliable as a bare join signal: a
    # Slack huddle, OBS, a VM, or a stray Meet tab can hold a device open for
    # hours, which used to read as "joined" and silently stand every meeting down
    # (voice still fired, but the overlay/nag never did — the bug). So we record
    # WHEN each device first went live and only trust it as a join if that was
    # recent (see joined_for). on_since is cleared the moment the device goes idle.
    dev = state.setdefault("devices", {})
    mic_active, cam_active = mic_in_use(), cam_in_use()
    for name, active in (("mic", mic_active), ("cam", cam_active)):
        if active:
            dev.setdefault(name, {})
            if not dev[name].get("on_since"):
                dev[name]["on_since"] = now.isoformat()
        else:
            dev[name] = {"on_since": None}
    mic_on_since = (datetime.fromisoformat(dev["mic"]["on_since"])
                    if dev.get("mic", {}).get("on_since") else None)
    cam_on_since = (datetime.fromisoformat(dev["cam"]["on_since"])
                    if dev.get("cam", {}).get("on_since") else None)
    zoom_live = zoom_in_meeting()

    maybe_wrapup(events, state, cfg, now,
                 in_call=mic_active or cam_active or zoom_live)

    live_keys = set()
    for ev in events:
        key, sid = ev["key"], safe_id(ev["key"])
        live_keys.add(key)
        mins_to = (ev["start"] - now).total_seconds() / 60

        # process any overlay button press
        choice = read_choice(sid)
        if choice in ("ack", "join"):
            state["acked"][key] = now.isoformat()
        elif choice and choice.startswith("snooze:"):
            mins = float(choice.split(":")[1])
            state["snooze"][key] = (now + timedelta(minutes=mins)).isoformat()

        level = alert_level(ev, cfg)
        if level == "skip":  # e.g. you declined this meeting
            continue
        if key in state["acked"]:
            continue
        if mins_to > max(lead_times) + 0.5:
            continue
        if mins_to < -cfg["overdue_nag_minutes"]:
            continue  # too long past start; gave up

        snooze_until = state["snooze"].get(key)
        snoozed = snooze_until and now < datetime.fromisoformat(snooze_until)

        # Has Sujit actually joined THIS meeting? (recency-aware — a device held
        # open for hours doesn't count; see joined_for.)
        joined = joined_for(ev["start"], now, mic_active=mic_active,
                            mic_on_since=mic_on_since, cam_active=cam_active,
                            cam_on_since=cam_on_since, zoom_live=zoom_live,
                            max_lead=max_lead)

        # spoken pre-alerts (fire each lead time once)
        fired = state["fired"].setdefault(key, {})
        if not snoozed and mins_to > 0:
            for lt in lead_times:
                if mins_to <= lt and str(lt) not in fired:
                    # mark larger lead times as moot so we don't stack
                    for bigger in lead_times:
                        if bigger >= lt:
                            fired[str(bigger)] = True
                    mins_phrase = f"{lt} minutes" if lt != 1 else "1 minute"
                    speak(pick("lead", cfg, title=ev["title"], mins=mins_phrase), cfg)
                    break

        # The full-screen overlay ALWAYS appears at overlay_lead_min and persists
        # with a live countdown. It is NOT gated on the mic/camera — suppressing the
        # visual interrupt on a flaky signal was the silent-failure bug. Once we
        # deliberately dismiss it (genuine join), `dismissed` stops it relaunching.
        # +0.5 = half a tick of slack: with 60s ticks, a bare `<= lead` check can
        # land just after the threshold and slip a whole minute late.
        rec = state["overlay"].get(key, {})
        had_overlay = pid_alive(rec.get("pid"))
        if (not snoozed and mins_to <= cfg["overlay_lead_min"] + 0.5
                and not had_overlay and not rec.get("dismissed")):
            pid = launch_overlay(sid, ev["title"], ev["start"].isoformat(),
                                 ev["url"], theme=cfg.get("overlay_theme", "midnight"),
                                 lead_min=cfg["overlay_lead_min"],
                                 snooze_min=cfg.get("snooze_min", 2),
                                 line=pick("overlay_line", cfg, title=ev["title"]),
                                 late_line=pick("overlay_line_late", cfg, title=ev["title"]))
            state["overlay"][key] = {"pid": pid, "launched": now.isoformat()}

        # Genuine join → stand down (dismiss overlay + stop nagging), but only once
        # the overlay has already had its turn on screen (it was alive coming into
        # this tick). That guarantees the popup shows at least once before any join
        # signal can cancel it — the visual interrupt can never be silently skipped.
        if joined and had_overlay:
            state["acked"][key] = now.isoformat()
            kill_overlay(rec.get("pid"))
            rec.update({"dismissed": True})
            rec.pop("pid", None)
            state["overlay"][key] = rec
            log.info("join detected for %r — standing down", ev["title"])
            continue

        # auto-open the link once, at start time
        if mins_to <= 0 and key not in state["opened"]:
            if ev["url"] and level == "full":   # only auto-open for accepted meetings
                open_url(ev["url"])
            speak(pick("starting_now", cfg, title=ev["title"]), cfg)
            state["opened"][key] = now.isoformat()
            fired["nag"] = now.isoformat()  # hold the first nag ~1 min after start

        # escalating overdue nag — ONLY for meetings you've accepted ('full').
        # For 'remind' (maybe / not-responded) we stop after the start nudge.
        # Skip if he's joined (the rare same-tick case the standdown above misses).
        if not snoozed and not joined and mins_to <= 0 and level == "full":
            last_nag = fired.get("nag")
            if not last_nag or (now - datetime.fromisoformat(last_nag)).total_seconds() >= 55:
                overdue_min = -mins_to
                tier = ("overdue_gentle" if overdue_min < 2
                        else "overdue_firm" if overdue_min < 5
                        else "overdue_upset")
                speak(pick(tier, cfg, title=ev["title"]), cfg)
                fired["nag"] = now.isoformat()

    # prune state for events no longer in window
    for bucket in ("fired", "overlay", "acked", "snooze", "opened", "wrapup"):
        for k in list(state[bucket]):
            if k not in live_keys and k != "calendar-error":
                # keep recently-acked briefly to avoid re-alerting; drop the rest
                state[bucket].pop(k, None)

    save_state(state)


def main() -> None:
    setup_logging()
    BASE.mkdir(parents=True, exist_ok=True)
    arg = sys.argv[1] if len(sys.argv) > 1 else "--tick"
    if arg == "--briefing":
        cfg = load_config(); tz = ZoneInfo(cfg["timezone"])
        speak_briefing(load_events(cfg, tz, feed_changed=False), cfg, tz)
        return
    if arg == "--status":
        state = load_state()
        print(json.dumps({
            "last_good_fetch": state.get("last_good_fetch"),
            "last_fetch_attempt": state.get("last_fetch_attempt"),
            "tracked_events": len(state.get("fired", {})),
        }, indent=2))
        return
    lock = acquire_lock()  # noqa: F841 (held for process lifetime)
    try:
        tick()
    except Exception:  # noqa: BLE001
        log.exception("tick crashed")
        raise


if __name__ == "__main__":
    main()
