# Meeting Assistant

A warm-but-nagging personal assistant that makes sure you actually join your
meetings — on your Mac (voice + auto-open + full-screen overlay + escalating
nag) and, via the phone-side setup below, in the car and on your wrist.

She speaks in a consistent caring voice whose **tone escalates**: gentle nudge →
firm → mildly upset (and always uses your name when annoyed). One of ~20 phrase
variations per situation is picked at random, so you never hear the same line
two days running.

## Setup on a fresh Mac

```bash
git clone https://github.com/sujeet100/tara.git ~/.meeting-assistant
cd ~/.meeting-assistant && ./install.sh
# then put your Google Calendar secret iCal URL in .env:
#   CALENDAR_ICAL_URL=https://calendar.google.com/calendar/ical/.../private-XXXX/basic.ics
```

## How it works (the design in one paragraph)

A **periodic** launchd agent (`brain.py`) runs every 60s as a fresh, short-lived
process — launchd is its watchdog, so it can't hang silently the way a daemon
can (that silent-failure mode is exactly the Dato problem we set out to kill).
Each tick reads a tiny cached event index, decides what to alert, fires voice +
a detached full-screen overlay, and exits. The overlay is its own GUI process
with a 1-second timer, so it persists and counts down on its own. A separate,
decoupled menu-bar app (`menubar.py`) shows health and preferences — if it dies
you lose the icon, never the alarms.

**Fail loud, not silent:** if the calendar can't be read for >60 min during work
hours, she says so out loud and throws a red overlay, instead of going quiet.

## Files

| File | Purpose |
|------|---------|
| `brain.py` | The periodic tick: fetch, decide, alert. |
| `overlay.swift` → `bin/overlay` | Full-screen attention window (themed, live countdown). |
| `miccheck.swift` → `bin/miccheck` | Detects if the mic is live = you're in a call (join detection). |
| `menubar.py` | Menu-bar health indicator + Preferences. |
| `phrases.json` | ~300 persona lines, 20 per situation. |
| `config.json` | All your settings. |
| `.env` | Your secret iCal feed URL (`CALENDAR_ICAL_URL`, chmod 600, gitignored). |
| `events.json` / `cache/last.ics` | Cached calendar (so ticks are instant). |
| `state.json` | What's already fired / acked / snoozed. |
| `logs/assistant.log` | What she's doing. |

## What she does

- **Pre-alerts** at 5 and 2 minutes before (voice).
- **Full-screen overlay** ~1 min before, with a live countdown and Join / I'm-in / Snooze buttons. Floats above everything, including full-screen apps.
- **Auto-opens** the Zoom/Meet/Teams link at start time (accepted meetings only).
- **Escalating nag** every minute after start until you join — detected automatically when your **mic goes live** (covers Zoom, Meet PWA in Brave, Arc, Teams) or you click a button.
- **Morning briefing** (~07:30) reads today's agenda, calling out **one-off** meetings first (the ones you forget) and reminding you of **unanswered invites**.
- **Lunch nudge** at the last good gap before afternoon meetings ("free until your 2 PM — go eat now").
- **RSVP-aware:** declined meetings are ignored; not-responded / maybe get a lighter touch (no auto-open, no nagging).

## Preferences (menu bar 🗓️)

Theme · Voice · Name frequency · Lunch on/off · Set calendar link · Set your
name · Read today's agenda · Preview theme · Test alert · Open config folder.
Changes write to `config.json` and take effect within a minute.

You can also edit `config.json` directly. Themes: `midnight`, `sunrise`,
`forest`, `grape`, `mono`. Preview one: `./preview-theme.sh sunrise` (or `all`).

## Voice

Neural **edge-tts** (`en-IN-NeerjaExpressiveNeural`) — free, no API key — with
macOS `say` (Tara) as an automatic **offline fallback** so a network blip never
loses a reminder.

## Controlling it

```bash
# pause for the day
launchctl bootout gui/$(id -u)/com.sujitk.meeting-assistant.brain
# resume
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.sujitk.meeting-assistant.brain.plist
# run a tick by hand / hear the briefing
~/.meeting-assistant/venv/bin/python ~/.meeting-assistant/brain.py --tick
~/.meeting-assistant/venv/bin/python ~/.meeting-assistant/brain.py --briefing
# health
~/.meeting-assistant/venv/bin/python ~/.meeting-assistant/brain.py --status
# logs
tail -f ~/.meeting-assistant/logs/assistant.log
# remove everything
~/.meeting-assistant/uninstall.sh
```

## Caveat

The Mac brain only runs while the Mac is awake — which is why the phone-side
layers below matter for the car and away-from-desk cases.

## Phone-side setup (do these once, on your iPhone)

1. **Apple Watch** — Watch app → Sounds & Haptics → **Prominent Haptics** on; add a 2nd alert per important event.
2. **CarPlay voice** — Settings → Notifications → **Announce Notifications** → on + CarPlay; enable **Calendar**.
3. **Siri agenda** — Settings → Calendar → Accounts → add Google. Then "Hey Siri, what's my schedule today?" works in the car (English).
