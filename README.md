# Tara — a warm, nagging meeting assistant for macOS

A personal assistant that makes sure you **actually join your meetings**. She
speaks to you, takes over your screen, opens the link for you, and — if you
still don't join — gets progressively, caringly upset about it.

Built because ordinary reminders failed me: I'd go deep into work, ignore every
banner and badge, and surface fifteen minutes into a meeting I'd missed. Worse,
my previous calendar tool failed *silently* when its auth expired — no popup, no
warning, just missed meetings. Tara is designed around three principles, in
priority order:

1. **Interrupt a sense you aren't using.** Voice in your ears and a full-screen
   overlay in your eyes — not another silent banner in a corner.
2. **Persist and escalate.** Don't fire once and give up; nag, escalating in
   tone, until you actually join.
3. **Fail loud, never silent.** If the calendar can't be read, she says so out
   loud and throws a red overlay. She never just goes quiet.

Her voice is constant — warm, caring, personally invested — but her **tone
escalates**: gentle nudge → firm → genuinely upset (she always uses your name
when she's annoyed). Every situation has ~20 phrase variations picked at
random, so you never hear the same line two days running.

## Requirements

- macOS 13+ (Apple Silicon or Intel), with Xcode Command Line Tools (`swiftc`)
- Python 3.10+
- A calendar that publishes an **iCal (.ics) feed URL** — Google Calendar's
  "Secret address in iCal format" works perfectly (no OAuth, never expires),
  and so does any other https .ics feed (Outlook publishes them too)

## Install

```bash
git clone https://github.com/sujeet100/tara.git ~/.meeting-assistant
cd ~/.meeting-assistant
./install.sh                          # venv, Swift helpers, launchd agents
venv/bin/python brain.py --setup      # guided: your name + calendar URL (validated live)
```

That's it. The brain ticks every minute from then on, surviving reboots.
Google Calendar feed URL: Settings → *your calendar* → **Integrate calendar** →
**Secret address in iCal format**. Treat it like a password — it's stored in
`.env` (chmod 600, gitignored).

## What she does

- **Morning briefing** (default 07:30): greeting, today's agenda with **one-off
  meetings called out first** (the ones you forget), then a nudge about invites
  you haven't answered.
- **Voice pre-alerts** at 5 and 2 minutes before each meeting, plus a small
  self-dismissing **corner toast** (click it to join).
- **Full-screen "Daybreak" overlay** 3 minutes before: themed sky, live
  countdown with a depleting progress ring, Join / I'm in / Snooze buttons,
  ⏎ joins, esc snoozes. One per screen. When the meeting starts without you,
  **the sky burns red and pulses** — the visuals escalate like her voice.
- **Auto-opens** the Meet/Zoom/Teams link at start time (accepted meetings only).
- **Escalating voice nag** after start — gentle, then firm, then upset — until
  you join or 12 minutes pass.
- **Join detection, app-agnostic:** your mic or camera going live *near meeting
  time* (Zoom, Meet in any browser, Teams — no permissions needed; device state
  only), or Zoom's in-call process, or the "I'm in" button. A mic held open for
  hours by some background app deliberately does **not** count.
- **Wrap-up warning** ~5 minutes before the *current* meeting ends when another
  follows soon: "about 5 minutes left — Design review is at 2:00."
- **Lunch nudge** at the last good gap before afternoon meetings; a caring
  warning if you're booked straight through.
- **RSVP-aware:** declined meetings are skipped entirely; tentative /
  not-responded get a lighter touch (no auto-open, no nagging).
- **Fail-loud:** calendar unreadable for >60 min during work hours → she says so
  and shows a red overlay, repeating every 30 min until fixed.

## The design in one paragraph

A **periodic** launchd agent (`brain.py`) runs every 60 seconds as a fresh,
short-lived process — launchd is its watchdog, so it cannot hang silently the
way a daemon can (that silent-failure mode is exactly what this project exists
to kill). Each tick reads a tiny cached event index (the 12 MB feed is parsed
only when it changes), decides what to alert, fires its channels, and exits.
The overlay and toast are detached GUI processes that live on their own; voice
runs through per-utterance workers that synthesize in parallel but **queue
playback** so announcements never talk over each other. A decoupled menu-bar
app (`menubar.py`, 🌸) shows health and preferences — if it dies you lose the
icon, never the alarms.

## Files

| File | Purpose |
|------|---------|
| `brain.py` | The periodic tick: fetch → decide → alert. Also `--setup`, `--briefing`, `--status`. |
| `voice.py` | Per-utterance voice worker (edge-tts, `say` fallback, queued playback). |
| `overlay.swift` → `bin/overlay` | Full-screen Daybreak alert (countdown ring, escalating sky). |
| `toast.swift` → `bin/toast` | Corner popup, self-dismissing, click-to-join. |
| `miccheck.swift` / `camcheck.swift` | Mic/camera-active join signals (device state only, no capture). |
| `menubar.py` | 🌸 health + Preferences + Stop/Resume. |
| `phrases.json` | The persona: ~20 lines per situation. Edit freely — this is where Tara lives. |
| `config.json` | All settings; the brain re-reads it every tick. |
| `.env` | Your secret iCal URL (`CALENDAR_ICAL_URL`). |

## Preferences

From the 🌸 menu: theme, voice, how often she uses your name, lunch reminders
on/off, calendar link, your name, read today's agenda, preview theme, test
alert, and **Stop/Resume Tara** (a hard off switch that survives reboots).

Or edit `config.json` directly — lead times, overlay lead, nag duration, work
hours, briefing time, lunch window, wrap-up window, toast lifetime, RSVP
behaviour, timezone (auto-detected if absent). Overlay themes: `midnight`,
`sunrise`, `forest`, `grape`, `mono`, `glass` — preview with
`./preview-theme.sh sunrise` (or `all`).

## Voice

Neural **edge-tts** (`en-IN-NeerjaExpressiveNeural` by default — pick any Edge
voice) with macOS `say` as an automatic offline fallback, so a network blip
never loses a reminder. Note: edge-tts uses Microsoft Edge's online TTS
unofficially — it's free and needs no key, but could break someday; the `say`
fallback keeps Tara talking if it does.

## Controlling it

```bash
venv/bin/python brain.py --tick        # run one tick by hand
venv/bin/python brain.py --briefing    # hear the morning briefing now
venv/bin/python brain.py --status      # health
tail -f logs/assistant.log
# pause / resume: use the 🌸 menu (Stop Tara / Resume Tara), or:
launchctl bootout gui/$(id -u)/com.tara-assistant.brain
./uninstall.sh                         # remove agents (keeps your files)
```

Tests: `venv/bin/python tests/test_join.py && venv/bin/python tests/test_wrapup.py`

## Caveats

- The Mac brain only runs while the Mac is awake. For the car and
  away-from-desk, set up the phone-side layers in **`IPHONE.md`** (Apple Watch
  prominent haptics, CarPlay Announce Notifications, Siri agenda).
- Just-added meetings can take a few minutes to appear in Google's secret feed.
- The menu-bar app runs as a plain script, so it won't appear in System
  Settings → "Allow in the Menu Bar", and its icon can hide behind the notch on
  a full bar (⌘-drag icons to make room).

## Make her yours

`config.json` sets your name, her name, and voice; `phrases.json` is her entire
personality — every line she can say, ~20 variants per situation, with
`{name}`/`{title}`/`{time}` placeholders. Rewrite it in your own language of
affection (or actual language — any edge-tts voice works). See `CLAUDE.md` for
the design rationale and extension guide.

MIT licensed.
