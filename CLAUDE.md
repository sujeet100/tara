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
- **Secret iCal URL** in `.env` as `CALENDAR_ICAL_URL` (chmod 600, gitignored; legacy `calendar-url.txt` still honoured as a fallback) — no OAuth, never expires. This is what kills Dato's auth-expiry problem. Read via `read_calendar_url()`. The feed carries timezones (events come in e.g. `Europe/Lisbon`) and RSVP `PARTSTAT` and `RRULE` — all handled.
- **Detached Swift overlay.** `bin/overlay` is its own GUI process with a 1s timer (live countdown), launched detached so it persists after the tick exits. The periodic brain never "holds" a window open.
- **Device-based join detection — rising-edge, never gates the overlay.** `bin/miccheck` (CoreAudio `kAudioDevicePropertyDeviceIsRunningSomewhere`) and `bin/camcheck` (CoreMediaIO equivalent) are app-agnostic "you're in a call" signals covering Zoom, Google Meet (PWA in Brave, or Arc), Teams. Neither needs a permission prompt (they read device state, capture nothing). Plus `zoom_in_meeting()` (pgrep `CptHost`) as a hard yes. **Critical lesson (June 2026 bug):** a bare "mic is on" check is a *false-positive trap* — a background **Slack huddle**, OBS, a VM, or a stray Meet tab holds a device open for hours, which read as "joined" and **silently stood every meeting down** (voice still fired because lead alerts are outside the nag window, but the overlay/nag never did). Fixed two ways, both in `joined_for()` + `tick()`: (1) the device only counts as a join if it went live *recently* — within ~`max(lead_times)+2` min of the meeting (we track each device's `on_since` in `state["devices"]`, cleared when it goes idle); (2) the full-screen overlay **always** launches at `overlay_lead_min` regardless of device state, and a genuine join only *dismisses* it after it's already had its turn on screen — so the visual interrupt can never be silently skipped (honours "fail loud, not silent"). Camera is a strong "really here" cue but Sujit doesn't always enable video, so it's an OR with the mic, never required. Manual "I'm in" button is still the fallback.
- **Decoupled menu-bar app.** `menubar.py` (rumps, `KeepAlive`) only *reads* `state.json` and *writes* `config.json`/`calendar-url.txt`. If it dies you lose the 🌸 icon, never the alarms. It runs as a plain script (not a bundled .app), so it won't show in System Settings → "Allow in the Menu Bar" — that's expected. Its icon hides behind the MacBook notch when the bar is full (⌘-drag to reveal).

## File map

| File | Purpose |
|------|---------|
| `brain.py` | Periodic tick: fetch → index → decide → alert (voice/overlay/open/nag), briefing, lunch, fail-loud. |
| `overlay.swift` → `bin/overlay` | Full-screen "Daybreak" countdown window, one per screen. Themes paint the *calm* sky; at start time every theme cross-fades to a universal burning-red **late palette** with a breathing pulse (visuals escalate like her voice). Progress ring depletes over `--lead` min; `⏎`=Join `esc`=Snooze; shows the platform chip and a Tara line (`--line`, swapped for `--lateline` when overdue); `--snooze <min>` labels the snooze button. All new args optional — old callers work. Recompile: `swiftc -O overlay.swift -o bin/overlay`. |
| `toast.swift` → `bin/toast` | Corner popup (top-right, self-dismissing after `toast.seconds`, click opens the meeting link, never steals focus). The GARNISH channel: Sujit tunes out corner notifications (Rize's popups are in the origin story), so it only ever *accompanies* voice for gentle moments (lead alerts, wrap-up, lunch) and is skipped when the full-screen overlay is up; anything that must land goes through voice + overlay. Recompile: `swiftc -O toast.swift -o bin/toast`. |
| `miccheck.swift` → `bin/miccheck` | Mic-active join signal. Recompile: `swiftc -O miccheck.swift -o bin/miccheck`. |
| `camcheck.swift` → `bin/camcheck` | Camera-active join signal (CoreMediaIO). Recompile: `swiftc -O camcheck.swift -o bin/camcheck`. |
| `remindercheck.swift` → `bin/remindercheck` | Dumps incomplete **Apple Reminders** as JSON (EventKit). Needs a one-time Reminders permission — the prompt only appears because an Info.plist is **linked into the binary**, so recompile with: `swiftc -O remindercheck.swift -o bin/remindercheck -Xlinker -sectcreate -Xlinker __TEXT -Xlinker __info_plist -Xlinker remindercheck-info.plist` (a recompile changes the binary's identity → macOS may re-ask once). |
| `audioroute.swift` → `bin/audioroute` | `check` = JSON of the default output device + transport (spots Bluetooth); `play <file> --device <id>` = play to a SPECIFIC device (afplay can't). Powers speaker mirroring. Recompile: `swiftc -O audioroute.swift -o bin/audioroute`. |
| `voice.py` | Detached per-utterance voice worker. Synthesizes in parallel (edge-tts → `say` fallback) but **serializes playback** via ticket files in `runtime/voiceq/` + an flock on `runtime/voice.lock`, with `voice_gap_sec` of silence between lines — without it, two announcements on one tick (briefing + lead alert) talked over each other. Stale tickets (>5 min) are ignored and the flock dies with its process, so the queue can't jam. Also: **strips emoji** before synthesis ('🌸 Standup' was read as 'cherry blossom standup'); `--soft` = the in-call register (quieter playback AND gentler synthesis: `in_call_voice` volume/rate/pitch); `--incall` = normal voice but no speaker mirroring; **speaker mirroring** = when the default output is Bluetooth and no call is live, the line ALSO plays on the built-in speakers via `bin/audioroute` — headphones on the desk were swallowing announcements (`speaker_mirror.enabled`). |
| `tests/test_join.py` | Plain-assert tests for `joined_for` (run: `venv/bin/python tests/test_join.py`; same pattern: `test_wrapup.py`, `test_reminders.py`, `test_voice_text.py`). |
| `menubar.py` | 🌸 menu-bar health + Preferences. |
| `phrases.json` | Persona lines, ~20 per situation, picked at random. |
| `config.json` | All settings. Brain re-reads it every tick. |
| `preview-theme.sh` | `./preview-theme.sh sunrise 8` or `all`. |
| LaunchAgents | `~/Library/LaunchAgents/com.tara-assistant.{brain,menubar}.plist` |

## Sujit's preferences — TONE, PERSONA, LANGUAGE (important)

These are settled decisions by the original author (Sujit) and ship as the
project's defaults. Honour them when editing phrases or behaviour. (Other users
customise via `config.json` — name, assistant_name, voice — and `phrases.json`.)

**Persona — "Tara":**
- Female assistant named **Tara**; the user is **Sujit**.
- Voice is **constant**: warm, caring, a little personally invested in him.
- **Tone escalates by context** (the voice-vs-tone principle): gentle nudge → firm → mildly *upset*. She "gets upset" when he doesn't join — he explicitly wants this. Never cruel; caring even when cross.
- **Always uses his name when annoyed** (`overdue_firm`, `overdue_upset`) — enforced in `pick()` via the `always_name` set.
- When **super annoyed** (`overdue_upset`), the line opens with his name then a **`...` pause** ("Sujit... now I'm genuinely upset...").
- Otherwise uses his name **"every now and then"**, not every line — capped by `name_frequency` (default 0.4).
- **Morning greeting ALWAYS uses his name** (`briefing_greeting` is in `always_name`), and there's **no comma** between greeting and name so it flows tight ("Good morning Sujit!" — he disliked the pause).
- **In-call register (July 2026, he asked for this — twice):** while ANY call is live (mic/cam/Zoom — the same `in_call` signal wrap-up uses), every announcement about *another* meeting goes **short + soft + CALM** — like a person leaning in, not an announcer. Two halves: (1) dedicated short phrase banks `lead_incall` / `starting_incall` / `overdue_incall`, all **purely informational — zero attitude**: the overdue one replaces the gentle→firm→upset tiers while he's mid-call, and after the first version shipped he explicitly said even a *quietly pointed* tone ("they're waiting", "don't make me get loud") was distracting mid-conversation, so those lines carry **no guilt, no urgency theatre**; the burning-red overlay carries ALL escalation during calls (`overdue_incall` is deliberately NOT in `always_name` — the name-when-annoyed rule doesn't apply because she isn't annoyed here); (2) voice.py's `--soft` flag synthesizes gentler (lower pitch, slower, quieter) AND switches to the **plain `en-IN-NeerjaNeural`** voice — the Expressive variant's emotional inflection was part of what annoyed him (`in_call_voice.edge_voice`). Don't "fix" the nag tiers or the expressive voice back in during calls.

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
5. **today's tasks** from Apple Reminders (with times where set) plus one line about overdue ones, then
6. a **closing sign-off** ("Thank you… have a good day") so he knows she's finished.

**Wrap-up warning** (July 2026): voice-only nudge ~5 min before the *current* meeting ends — "about 5 minutes left, {next} is at {time}" — the mirror image of the join nag, for back-to-back days. Deliberately narrow so it never becomes noise: once per meeting, only if he's actually in it (acked, or mic/cam/Zoom live), and only when another meeting starts within `wrap_up.next_within_min` of this one ending; if nothing follows, overrunning is his call and Tara stays quiet. Config `wrap_up` {enabled, lead_min, next_within_min}; phrases in `wrap_up`; tests in `tests/test_wrapup.py`.

**Lunch:** he forgets lunch when meetings sneak up. Nudge him at the **last good gap before an afternoon meeting** ("free until your 2 PM — go eat now"). Window `12:30–14:00`, min gap 20 min. If back-to-back through lunch, one caring "don't skip lunch" warning.

**Task reminders (July 2026):** Apple Reminders is the task store — he adds tasks by voice from phone/watch ("Hey Siri, remind me…"), and **recurring reminders cover scheduled chores** (timesheet every Friday, feedback cycles) since each occurrence comes back with a fresh `id@due` key. `bin/remindercheck` dumps incomplete reminders each tick; a **timed** task gets one spoken line as it comes due + one follow-up (`follow_up_min`) if still incomplete — completing it in Reminders is the ack. Tasks that came due long ago (`window_min`, Mac asleep) are marked **stale silently** — never greet him with a barrage of ancient nags; the briefing covers them instead (due-today list + one overdue line). **Date-only tasks never fire a timed alert**, they belong to the briefing. `fetch_reminders` returns **None** (not `[]`) when access fails, so a TCC hiccup can't wipe announce-state; failures back off `retry_fail_min`. Tests: `tests/test_reminders.py`.

**Bluetooth-headphones trap (July 2026):** headphones *connected but not worn* swallowed announcements. True on-head detection isn't possible for generic BT headphones, so voice.py **mirrors** every line to the built-in speakers (via `bin/audioroute play`) whenever the default output transport is Bluetooth **and no call is live** (mid-call, audio must stay in his ear — `--incall`/`--soft` suppress mirroring). Worst case he hears it twice; he never hears silence.

**RSVP-aware** (he asked for this): read his `PARTSTAT` per event — **declined → skip entirely**, **not-responded / tentative → remind only** (lead + overlay, no auto-open, no escalating nag), **accepted → full**.

**Overlay:** full-screen "Daybreak" design (he picked direction A of three mockups, July 2026): themed sky + horizon glow while there's time, progress ring around the countdown, then at start time the sky **burns red and pulses** — the visual escalates exactly like her voice does. Join / I'm-in / Snooze buttons (snooze length = `snooze_min`), keyboard shortcuts, platform chip, and one of ~20 `overlay_line` phrases on screen (swaps to an `overlay_line_late` upset line when overdue — that category is in `always_name`). Current theme **sunrise**. Themes: `midnight, sunrise, forest, grape, mono, glass` (glass = frosted, translucent over the screen); the late palette is deliberately **universal** across themes — an alarm should be unambiguous. Menu-bar icon is **🌸**.

## config.json reference

`name`, `assistant_name`, `name_frequency` (0–1), `my_email` (for RSVP),
`tts` {engine edge|say, edge_voice, edge_rate, say_voice, say_rate}, `lead_times_min`,
`overlay_lead_min` (default 3; brain adds +0.5 min slack so a 60s tick can't slip it a minute late),
`voice_gap_sec` (silence between queued announcements), `overdue_nag_minutes`, `overlay_theme`, `lunch` {enabled, earliest,
latest, min_minutes}, `rsvp` {accepted/needs_action/tentative/declined → full|remind|skip},
`work_hours`, `briefing_time`, `fetch_interval_sec`, `stale_alert_after_min`,
`in_call_voice` {enabled, volume 0–1, edge_volume/edge_rate/edge_pitch — the soft in-call register},
`speaker_mirror` {enabled — mirror to built-in speakers when output is Bluetooth and no call is live},
`reminders` {enabled, lists ([] = all), window_min, follow_up_min, retry_fail_min}.

## How to extend

- **New phrase category:** add an array to `phrases.json` (aim for ~20), call `pick("category", cfg, **kw)`. Placeholders: `{name} {assistant} {title} {mins} {time} {n} {meetings}`. Add to `always_name` in `brain.py` if it must always include his name.
- **New theme:** add to `THEMES` in `overlay.swift` (top/bottom/accent/glow — this is the *calm* sky only; the late palette is universal, don't add per-theme late variants), recompile, then add to `THEMES` in `menubar.py` and the `all` loop in `preview-theme.sh`.
- **New output channel** (e.g. phone push): channels are just functions called from the tick — add alongside `speak()` / `launch_overlay()` / `show_toast()`.
- After editing `brain.py`/`phrases.json`: no restart needed (each tick is a fresh process). After editing `menubar.py` or `overlay.swift`: `launchctl kickstart -k gui/$(id -u)/com.tara-assistant.menubar` and/or recompile.

## Run / control / debug

```bash
VENV=~/.meeting-assistant/venv/bin/python
$VENV ~/.meeting-assistant/brain.py --tick       # run one tick by hand
$VENV ~/.meeting-assistant/brain.py --briefing    # hear the morning briefing now
$VENV ~/.meeting-assistant/brain.py --status      # health
$VENV ~/.meeting-assistant/brain.py --tasks       # what remindercheck sees (JSON)
tail -f ~/.meeting-assistant/logs/assistant.log
launchctl bootout gui/$(id -u)/com.tara-assistant.brain    # pause
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
- Recompiling `remindercheck` changes its code signature, so macOS may show the Reminders permission prompt again (once). If task reminders go quiet after a recompile, run `brain.py --tasks` and check System Settings → Privacy & Security → Reminders.
