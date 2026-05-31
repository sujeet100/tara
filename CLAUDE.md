# CLAUDE.md — Meeting Assistant

Context for future work on this app. Read this first before changing anything.

## What this is and why it exists

A personal assistant ("**Tara**") that makes sure **Sujit** actually joins his
meetings and doesn't lose track of the day. Built because the usual reminders
fail him: he goes deep into work, ignores notifications (Slack, email, Dato,
Rize), and sometimes only notices 10–15 minutes late. Dato also fails *silently*
when its calendar auth expires — no popup, no warning — and he misses meetings.

So the three guiding principles, in priority order:

1. **Interrupt a sense he isn't using** — voice (ears) and a full-screen overlay, not another silent banner.
2. **Persist / escalate** — don't fire once; nag, escalating in tone, until he actually joins.
3. **Fail loud, not silent** — if the calendar can't be read, say so out loud. Never go quiet like Dato did.

The Mac is the "brain" for deep-work-at-desk. The car / away-from-desk cases are
covered by phone-side setup (Apple Watch haptics, CarPlay "Announce
Notifications", Siri agenda) — see README. The Mac brain only runs while the Mac
is awake; that's the known gap the phone layers fill.

## Architecture (and the reasoning — don't undo these without cause)

- **Periodic `launchd` agent, NOT a daemon.** `brain.py` runs every 60s as a fresh, short-lived process (`StartInterval 60`, **no `KeepAlive`**). Chosen deliberately: a long-running daemon can **hang silently** (alive but stuck), and `KeepAlive` only detects *exit*, not hangs — that's the exact silent-failure mode we're killing. A periodic process can't hang silently; launchd is the watchdog and each tick is independent. Precision (sub-minute) is recovered in code, not by switching to a daemon.
- **Tiny event index.** Parsing the 12 MB iCal feed takes ~4s, so it's done only when the feed changes (or every few hours) into `events.json`; per-minute ticks read that and stay ~0.2s. Don't move the parse back into the per-tick path.
- **Secret iCal URL** (`calendar-url.txt`, chmod 600) — no OAuth, never expires. This is what kills Dato's auth-expiry problem. The feed carries timezones (events come in e.g. `Europe/Lisbon`) and RSVP `PARTSTAT` and `RRULE` — all handled.
- **Detached Swift overlay.** `bin/overlay` is its own GUI process with a 1s timer (live countdown), launched detached so it persists after the tick exits. The periodic brain never "holds" a window open.
- **Mic-based join detection.** `bin/miccheck` reads CoreAudio `kAudioDevicePropertyDeviceIsRunningSomewhere` — app-agnostic "you're in a call" signal that covers Zoom, Google Meet (PWA in Brave, or Arc), Teams. Needs no mic permission. Manual "I'm in" button is the fallback.
- **Decoupled menu-bar app.** `menubar.py` (rumps, `KeepAlive`) only *reads* `state.json` and *writes* `config.json`/`calendar-url.txt`. If it dies you lose the 🌸 icon, never the alarms. It runs as a plain script (not a bundled .app), so it won't show in System Settings → "Allow in the Menu Bar" — that's expected. Its icon hides behind the MacBook notch when the bar is full (⌘-drag to reveal).

## File map

| File | Purpose |
|------|---------|
| `brain.py` | Periodic tick: fetch → index → decide → alert (voice/overlay/open/nag), briefing, lunch, fail-loud. |
| `overlay.swift` → `bin/overlay` | Full-screen themed countdown window. Recompile: `swiftc -O overlay.swift -o bin/overlay`. |
| `miccheck.swift` → `bin/miccheck` | Mic-active = join detection. |
| `menubar.py` | 🌸 menu-bar health + Preferences. |
| `phrases.json` | Persona lines, ~20 per situation, picked at random. |
| `config.json` | All settings. Brain re-reads it every tick. |
| `preview-theme.sh` | `./preview-theme.sh sunrise 8` or `all`. |
| LaunchAgents | `~/Library/LaunchAgents/com.sujitk.meeting-assistant.{brain,menubar}.plist` |

## Sujit's preferences — TONE, PERSONA, LANGUAGE (important)

These are settled decisions. Honour them when editing phrases or behaviour.

**Persona — "Tara":**
- Female assistant named **Tara**; the user is **Sujit**.
- Voice is **constant**: warm, caring, a little personally invested in him.
- **Tone escalates by context** (the voice-vs-tone principle): gentle nudge → firm → mildly *upset*. She "gets upset" when he doesn't join — he explicitly wants this. Never cruel; caring even when cross.
- **Always uses his name when annoyed** (`overdue_firm`, `overdue_upset`) — enforced in `pick()` via the `always_name` set.
- When **super annoyed** (`overdue_upset`), the line opens with his name then a **`...` pause** ("Sujit... now I'm genuinely upset...").
- Otherwise uses his name **"every now and then"**, not every line — capped by `name_frequency` (default 0.4).
- **Morning greeting ALWAYS uses his name** (`briefing_greeting` is in `always_name`), and there's **no comma** between greeting and name so it flows tight ("Good morning Sujit!" — he disliked the pause).

**Language:**
- **English only.** Marathi was considered and **dropped** (Siri can't speak Marathi; event titles are English anyway). If revisited: free neural Marathi exists via `edge-tts mr-IN-AarohiNeural/ManoharNeural`, or local Kokoro/Qwen.
- Voice engine: **edge-tts `en-IN-NeerjaExpressiveNeural`** (free, neural, Indian-English, expressive). He compared options and picked this. macOS `say` (`Tara` voice) is the automatic **offline fallback**.

**Variety:**
- ~**20 variations per situation**, chosen at random — he does **not** want to hear the same sentence daily. Keep this density when adding categories.

**Morning briefing structure** (he designed this):
1. **Greeting** (varied, with his name) +
2. an uplifting **"what a beautiful day / life is beautiful"** line, then
3. the **agenda** — **one-off meetings called out first** (the ones he forgets), then recurring, then
4. a nudge about **invites he hasn't responded to**, then
5. a **closing sign-off** ("Thank you… have a good day") so he knows she's finished.

**Lunch:** he forgets lunch when meetings sneak up. Nudge him at the **last good gap before an afternoon meeting** ("free until your 2 PM — go eat now"). Window `12:30–14:00`, min gap 20 min. If back-to-back through lunch, one caring "don't skip lunch" warning.

**RSVP-aware** (he asked for this): read his `PARTSTAT` per event — **declined → skip entirely**, **not-responded / tentative → remind only** (lead + overlay, no auto-open, no escalating nag), **accepted → full**.

**Overlay:** full-screen, themed, live countdown, Join / I'm-in / Snooze buttons. Current theme **sunrise**. Themes: `midnight, sunrise, forest, grape, mono, glass` (glass = frosted, translucent over the screen). Menu-bar icon is **🌸**.

## config.json reference

`name`, `assistant_name`, `name_frequency` (0–1), `my_email` (for RSVP),
`tts` {engine edge|say, edge_voice, edge_rate, say_voice, say_rate}, `lead_times_min`,
`overlay_lead_min`, `overdue_nag_minutes`, `overlay_theme`, `lunch` {enabled, earliest,
latest, min_minutes}, `rsvp` {accepted/needs_action/tentative/declined → full|remind|skip},
`work_hours`, `briefing_time`, `fetch_interval_sec`, `stale_alert_after_min`.

## How to extend

- **New phrase category:** add an array to `phrases.json` (aim for ~20), call `pick("category", cfg, **kw)`. Placeholders: `{name} {assistant} {title} {mins} {time} {n} {meetings}`. Add to `always_name` in `brain.py` if it must always include his name.
- **New theme:** add to `THEMES` in `overlay.swift` (recompile), to `THEMES` in `menubar.py`, and to the `all` loop in `preview-theme.sh`.
- **New output channel** (e.g. phone push): channels are just functions called from the tick — add alongside `speak()` / `launch_overlay()`.
- After editing `brain.py`/`phrases.json`: no restart needed (each tick is a fresh process). After editing `menubar.py` or `overlay.swift`: `launchctl kickstart -k gui/$(id -u)/com.sujitk.meeting-assistant.menubar` and/or recompile.

## Run / control / debug

```bash
VENV=~/.meeting-assistant/venv/bin/python
$VENV ~/.meeting-assistant/brain.py --tick       # run one tick by hand
$VENV ~/.meeting-assistant/brain.py --briefing    # hear the morning briefing now
$VENV ~/.meeting-assistant/brain.py --status      # health
tail -f ~/.meeting-assistant/logs/assistant.log
launchctl bootout gui/$(id -u)/com.sujitk.meeting-assistant.brain    # pause
~/.meeting-assistant/uninstall.sh                 # remove agents (keeps files)
```

## Backlog / ideas for future improvement

- **Marathi morning briefing** via cloud/local neural TTS (edge-tts mr-IN, or Kokoro/Qwen local) — he'd like it but English is fine for now.
- **Phone push** (Pushover "emergency" repeat-until-ack, or ntfy) so nags reach him away from the Mac — pairs with iOS "Announce Notifications" to speak over CarPlay.
- **Brain that runs when the Mac is asleep** (the driving gap) — move the brain to a small always-on service, or lean fully on the phone layers.
- **Local TTS** (Kokoro `af_*` / Qwen3) for fully-offline, private voice — only worth the setup cost if edge-tts's online dependency becomes a problem.
- **Proper .app bundle** (Swift or py2app) so the menu-bar app registers in System Settings and isn't notch-buried.
- **More RSVP/scope controls in the menu**, per-meeting overrides, snooze tuning.
- **Local LLM** to make her phrasing fully generative instead of a fixed bank (would remove the "20 variations" ceiling).

## Caveats

- Mac must be awake for the brain. Phone layers cover the rest.
- edge-tts needs internet (falls back to `say` offline) and is an unofficial use of Edge voices — could break; that's the argument for a local engine later.
- Secret-feed changes can lag a few minutes on Google's side for just-added meetings.
