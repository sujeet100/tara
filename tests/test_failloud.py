"""Tests for the fail-loud path after the Mac has been asleep for days.

The failure these cover is the one Tara exists to avoid, inverted: instead of
going quiet she became noise. A slow 12 MB feed timed out, every re-alert spawned
another detached overlay nobody tracked, and voice workers suspended by system
sleep queued up and replayed days of "I can't read your calendar" on wake — after
the calendar was already back. Noise trains him to ignore her, so an alarm must
appear once, stop when the fault clears, and never speak about a stale moment."""

import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import brain  # noqa: E402

TZ = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 9, 12, 12, 0, tzinfo=TZ)
CFG = dict(brain.DEFAULT_CONFIG)

spoken: list[str] = []
launched: list[str] = []
killed: list[int] = []

brain.pick = lambda cat, cfg, **kw: cat
brain.speak = lambda text, cfg, in_call=False: spoken.append(text)
brain.within_work_hours = lambda now, cfg: True
brain.screen_awake = lambda: True          # stubbed per-test where it matters
brain.pid_alive = lambda pid: pid in ALIVE
brain.kill_overlay = lambda pid: killed.append(pid)


def fake_launch(safe_id, title, start_iso, url, **kw):
    launched.append(safe_id)
    pid = 1000 + len(launched)
    ALIVE.add(pid)
    return pid


ALIVE: set[int] = set()
brain.launch_overlay = fake_launch


def reset():
    spoken.clear()
    launched.clear()
    killed.clear()
    ALIVE.clear()


def stale_state(hours=48):
    """A Mac that's been properly up for a while and can't read its calendar."""
    return {"last_good_fetch": (NOW - timedelta(hours=hours)).isoformat(),
            "up_since": (NOW - timedelta(minutes=30)).isoformat(),
            "overlay": {}}


def at(minutes):
    """Freeze brain's clock `minutes` after NOW."""
    moment = NOW + timedelta(minutes=minutes)

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return moment
    brain.datetime = Clock
    return moment


# --- one alarm window, however long the outage runs ------------------------ #
reset()
st = stale_state()
at(0)
brain.fail_loud_check(st, CFG, TZ)
assert launched == ["calendar-error"], launched
assert len(spoken) == 1
first_pid = st["overlay"]["calendar-error"]["pid"]

at(35)  # past stale_realert_every_min: she speaks again...
brain.fail_loud_check(st, CFG, TZ)
assert len(spoken) == 2, "she must keep saying it — that's the fail-loud promise"
assert launched == ["calendar-error"], "...but must NOT stack another window"

at(70)
brain.fail_loud_check(st, CFG, TZ)
assert len(spoken) == 3
assert launched == ["calendar-error"]

# a window the user closed by hand is replaced on the next re-alert
ALIVE.discard(first_pid)
at(105)
brain.fail_loud_check(st, CFG, TZ)
assert launched == ["calendar-error"] * 2, "closed window should come back"

# --- recovery takes the alarm off screen ----------------------------------- #
live_pid = st["overlay"]["calendar-error"]["pid"]
brain.feed_recovered(st, at(110))
assert killed == [live_pid], f"the live overlay must be dismissed, killed={killed}"
assert "calendar-error" not in st["overlay"]
assert "last_stale_alert" not in st
assert st["last_good_fetch"] == at(110).isoformat()

# --- a sleeping Mac is never alarmed at ------------------------------------ #
# macOS dark-wakes hourly with the lid shut and launchd ticks us inside that
# window. Every such tick stands alone, so the up-clock never gets old enough to
# alarm — which is the whole point: nobody is there to hear or see it.
reset()
st = {"last_good_fetch": (NOW - timedelta(hours=48)).isoformat(), "overlay": {}}
for hour in range(6):                       # six lonely dark-wake ticks
    at(hour * 60)
    assert brain.note_tick(st, TZ) is True, "an isolated tick means it was asleep"
    brain.fail_loud_check(st, CFG, TZ)
assert spoken == [], "a closed laptop must never be shouted at"
assert launched == [], "and must never collect overlays to dismiss later"

# --- ...but a minute after he opens the lid, she screams ------------------- #
at(6 * 60)                                  # the lid-open tick: quiet, and retries
assert brain.note_tick(st, TZ) is True
assert "last_fetch_attempt" not in st, "a fresh run must retry the feed at once"
brain.fail_loud_check(st, CFG, TZ)
assert spoken == [], "give the calendar its minute before calling it dead"

at(6 * 60 + 1)                              # 60s later, still ticking, still broken
assert brain.note_tick(st, TZ) is False, "a 60s tick continues the run"
brain.fail_loud_check(st, CFG, TZ)
assert len(spoken) == 1, "one minute up and still unreadable → alarm"
assert launched == ["calendar-error"]

# a normal 60s tick doesn't clear the fetch back-off or restart the up-clock
reset()
st = {"last_tick": at(0).isoformat(), "up_since": at(0).isoformat(),
      "last_fetch_attempt": NOW.isoformat()}
at(1)
assert brain.note_tick(st, TZ) is False
assert st["last_fetch_attempt"] == NOW.isoformat()
assert st["up_since"] == at(0).isoformat(), "an unbroken run keeps its start time"

# a multi-day gap restarts it, and forces an immediate retry
st = {"last_tick": at(0).isoformat(), "up_since": (NOW - timedelta(days=9)).isoformat(),
      "last_fetch_attempt": NOW.isoformat()}
at(60 * 24 * 3)
assert brain.note_tick(st, TZ) is True
assert "last_fetch_attempt" not in st
assert st["up_since"] == at(60 * 24 * 3).isoformat()

# --- a dark wake long enough to tick twice is caught by the screen check ---- #
reset()
st = {"last_good_fetch": (NOW - timedelta(hours=48)).isoformat(), "overlay": {}}
at(0)
brain.note_tick(st, TZ)
at(2)
brain.note_tick(st, TZ)                     # continuous ticks, but the screen is off
brain.screen_awake = lambda: False
brain.fail_loud_check(st, CFG, TZ)
assert spoken == [] and launched == [], "nothing to see means nothing to say"
brain.screen_awake = lambda: True
brain.fail_loud_check(st, CFG, TZ)
assert len(spoken) == 1, "screen back on, calendar still dead → alarm"

print("fail-loud tests passed")
