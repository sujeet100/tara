#!/usr/bin/env python3
"""Menu-bar app: glanceable health + a Preferences menu.

DECOUPLED from the brain on purpose — it only *reads* the brain's state.json for
health and *writes* config.json / calendar-url.txt for preferences. If this app
crashes you lose the menu icon, never the alarms. The brain re-reads config.json
every tick, so changes here take effect within a minute.
"""

import json
import os
import stat
import subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import rumps

BASE = Path.home() / ".meeting-assistant"
CONFIG = BASE / "config.json"
URLFILE = BASE / "calendar-url.txt"   # legacy
ENV_FILE = BASE / ".env"
STATE = BASE / "state.json"
INDEX = BASE / "events.json"
VENV_PY = BASE / "venv" / "bin" / "python"
BRAIN = BASE / "brain.py"
PREVIEW = BASE / "preview-theme.sh"

THEMES = ["midnight", "sunrise", "forest", "grape", "mono", "glass"]
VOICES = [
    ("Neerja Expressive (neural)", "edge", "en-IN-NeerjaExpressiveNeural"),
    ("Neerja (neural)", "edge", "en-IN-NeerjaNeural"),
    ("Tara (offline)", "say", "Tara"),
]


def load_cfg() -> dict:
    try:
        return json.loads(CONFIG.read_text())
    except Exception:
        return {}


def save_cfg(cfg: dict) -> None:
    CONFIG.write_text(json.dumps(cfg, indent=2))


class MeetingAssistant(rumps.App):
    def __init__(self):
        super().__init__("🌸", quit_button=None)
        self.status_item = rumps.MenuItem("Loading…")
        self.health_item = rumps.MenuItem("")
        self.build_menu()
        rumps.Timer(self.refresh, 5).start()

    # ---- menu construction -------------------------------------------------
    def build_menu(self):
        cfg = load_cfg()
        self.menu.clear()
        items = [self.status_item, self.health_item, rumps.separator]

        theme_menu = rumps.MenuItem("Theme")
        cur_theme = cfg.get("overlay_theme", "midnight")
        for t in THEMES:
            it = rumps.MenuItem(t.capitalize(), callback=self._set_theme(t))
            it.state = 1 if t == cur_theme else 0
            theme_menu.add(it)
        items.append(theme_menu)

        voice_menu = rumps.MenuItem("Voice")
        tts = cfg.get("tts", {})
        for label, engine, voice in VOICES:
            it = rumps.MenuItem(label, callback=self._set_voice(engine, voice))
            key = tts.get("edge_voice") if engine == "edge" else tts.get("say_voice")
            it.state = 1 if (engine == tts.get("engine") and voice == key) else 0
            voice_menu.add(it)
        items.append(voice_menu)

        freq_menu = rumps.MenuItem("Name frequency")
        cur_freq = cfg.get("name_frequency", 0.4)
        for label, val in [("Never", 0.0), ("Rarely", 0.2), ("Sometimes", 0.4),
                           ("Often", 0.7), ("Always", 1.0)]:
            it = rumps.MenuItem(label, callback=self._set_freq(val))
            it.state = 1 if abs(cur_freq - val) < 0.01 else 0
            freq_menu.add(it)
        items.append(freq_menu)

        lunch = rumps.MenuItem("Lunch reminders", callback=self.toggle_lunch)
        lunch.state = 1 if cfg.get("lunch", {}).get("enabled", True) else 0
        items.append(lunch)

        items += [
            rumps.separator,
            rumps.MenuItem("Set calendar link…", callback=self.set_calendar),
            rumps.MenuItem("Set your name…", callback=self.set_name),
            rumps.separator,
            rumps.MenuItem("Read today's agenda", callback=self.read_agenda),
            rumps.MenuItem("Preview this theme", callback=self.preview_theme),
            rumps.MenuItem("Test alert", callback=self.test_alert),
            rumps.separator,
            rumps.MenuItem("Open config folder", callback=self.open_folder),
            rumps.MenuItem("Quit", callback=rumps.quit_application),
        ]
        for it in items:
            self.menu.add(it)

    # ---- preference callbacks ---------------------------------------------
    def _set_theme(self, theme):
        def cb(_):
            cfg = load_cfg(); cfg["overlay_theme"] = theme; save_cfg(cfg); self.build_menu()
        return cb

    def _set_voice(self, engine, voice):
        def cb(_):
            cfg = load_cfg()
            tts = cfg.setdefault("tts", {})
            tts["engine"] = engine
            if engine == "edge":
                tts["edge_voice"] = voice
            else:
                tts["say_voice"] = voice
            save_cfg(cfg); self.build_menu()
        return cb

    def _set_freq(self, val):
        def cb(_):
            cfg = load_cfg(); cfg["name_frequency"] = val; save_cfg(cfg); self.build_menu()
        return cb

    def toggle_lunch(self, _):
        cfg = load_cfg()
        lunch = cfg.setdefault("lunch", {})
        lunch["enabled"] = not lunch.get("enabled", True)
        save_cfg(cfg); self.build_menu()

    def _read_env(self, key):
        if ENV_FILE.exists():
            for line in ENV_FILE.read_text().splitlines():
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    if k.strip() == key:
                        return v.strip().strip('"').strip("'")
        if URLFILE.exists():
            return URLFILE.read_text().strip()
        return ""

    def set_calendar(self, _):
        current = self._read_env("CALENDAR_ICAL_URL")
        resp = rumps.Window(
            message="Paste your Google Calendar 'Secret address in iCal format' "
                    "(must contain 'private-' and end in .ics):",
            title="Calendar link", default_text=current,
            ok="Save", cancel="Cancel", dimensions=(440, 60)).run()
        if not resp.clicked:
            return
        url = resp.text.strip()
        if not (url.startswith("https://calendar.google.com/calendar/ical/") and url.endswith(".ics")):
            rumps.alert("That doesn't look like a Google iCal URL.\n\n"
                        "It should start with https://calendar.google.com/calendar/ical/ "
                        "and end in .ics")
            return
        ENV_FILE.write_text(f"CALENDAR_ICAL_URL={url}\n")
        os.chmod(ENV_FILE, stat.S_IRUSR | stat.S_IWUSR)  # 600
        # force a fresh fetch next tick
        try:
            state = json.loads(STATE.read_text())
            state.pop("last_fetch_attempt", None)
            STATE.write_text(json.dumps(state, indent=2, default=str))
        except Exception:
            pass
        rumps.alert("Calendar link saved. I'll re-read it within a minute.")

    def set_name(self, _):
        cfg = load_cfg()
        resp = rumps.Window(message="What should I call you?", title="Your name",
                            default_text=cfg.get("name", ""), ok="Save", cancel="Cancel",
                            dimensions=(260, 24)).run()
        if resp.clicked and resp.text.strip():
            cfg["name"] = resp.text.strip(); save_cfg(cfg)

    # ---- actions -----------------------------------------------------------
    def read_agenda(self, _):
        subprocess.Popen([str(VENV_PY), str(BRAIN), "--briefing"])

    def preview_theme(self, _):
        theme = load_cfg().get("overlay_theme", "midnight")
        subprocess.Popen(["/bin/bash", str(PREVIEW), theme])

    def test_alert(self, _):
        from datetime import timedelta, timezone
        start = (datetime.now(timezone.utc) + timedelta(seconds=12)).astimezone().isoformat()
        theme = load_cfg().get("overlay_theme", "midnight")
        subprocess.Popen([str(BASE / "bin" / "overlay"),
                          "--id", "test", "--title", "Test Meeting", "--start", start,
                          "--url", "https://meet.google.com/abc-defg-hij",
                          "--mode", "meeting", "--theme", theme, "--runtime", str(BASE / "runtime")])

    def open_folder(self, _):
        subprocess.Popen(["/usr/bin/open", str(BASE)])

    # ---- health refresh ----------------------------------------------------
    def refresh(self, _):
        cfg = load_cfg()
        tz = ZoneInfo(cfg.get("timezone", "Asia/Kolkata"))
        now = datetime.now(tz)
        try:
            state = json.loads(STATE.read_text())
        except Exception:
            state = {}

        healthy = True
        lg = state.get("last_good_fetch")
        if lg:
            age = (now - datetime.fromisoformat(lg)).total_seconds() / 60
            if age > 60:
                healthy = False
                self.health_item.title = f"⚠️ Calendar not read for {int(age)}m"
            else:
                self.health_item.title = f"✓ Calendar read {int(age)}m ago"
        else:
            healthy = False
            self.health_item.title = "⚠️ Calendar never read"

        nxt = None
        try:
            events = json.loads(INDEX.read_text())["events"]
            future = sorted((e for e in events if datetime.fromisoformat(e["start"]) > now),
                            key=lambda e: e["start"])
            nxt = future[0] if future else None
        except Exception:
            pass

        if nxt:
            s = datetime.fromisoformat(nxt["start"])
            mins = int((s - now).total_seconds() / 60)
            self.status_item.title = f"Next: {nxt['title'][:28]} · {s:%-I:%M %p} ({mins}m)"
        else:
            self.status_item.title = "No upcoming meetings"

        if not healthy:
            self.title = "⚠️"
        elif nxt and mins <= 60:
            self.title = f"🌸 {mins}m"
        else:
            self.title = "🌸"


if __name__ == "__main__":
    MeetingAssistant().run()
