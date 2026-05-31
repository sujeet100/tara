# Tara on iPhone (driving + voice agenda)

iOS won't allow a Mac-style nagger app (CarPlay app categories are restricted,
background is limited). But the two things that matter while driving — hearing
your **agenda** and your **meeting reminders** — are fully doable natively with
Shortcuts + Announce Notifications. This uses Siri's voice (not Tara's Neerja),
needs no Mac, and works anywhere.

## Step 0 — sync Google into Apple Calendar (required)

Shortcuts, Siri, and Announce Notifications all read the **iOS Calendar**, not
Google directly. One-time:

**Settings → Calendar → Accounts → Add Account → Google →** sign in → toggle
**Calendars ON.** (Live sync, nothing duplicated.)

---

## The "Today's Agenda" shortcut

### Option A — import the prebuilt file (may need fixing)

`shortcuts/Todays Agenda.shortcut` in this repo is a hand-authored, **unsigned**
shortcut. It may import cleanly or may error on the calendar filter — untested
from a Mac, so treat it as a head start, not a guarantee.

1. Get the file onto your iPhone (AirDrop from Finder, iCloud Drive, or email).
2. On iPhone: **Settings → Shortcuts → Allow Untrusted Shortcuts → On**
   (this toggle only appears after you've run *any* one shortcut once).
3. Open the file → **Add Shortcut**. If it imports with red "broken action"
   warnings, fall back to Option B (it's only ~5 taps).

### Option B — build it by hand (reliable, ~5 taps)

Shortcuts app → **+** → name it **`Today's Agenda`** → add:

1. **Find Calendar Events** — Start Date `is Today`, Sort by `Start Date`, `Ascending`.
2. **Speak Text** — type only: `Good morning Sujit. Here is your day.` → expand options → **Wait Until Finished: On**, Language **English (India)**.
3. **Speak Text** — insert **only** the `Calendar Events` variable and **don't tap the chip** (leaving it whole makes it read each event *with its time*). → **Wait Until Finished: On**.

> Two separate Speak Text actions = you never mix text + a variable in one field
> (that's what was wiping your greeting — inserting a variable replaces *selected*
> text, so tap once to place the cursor, never select-all).

Tap ▶︎ to test, then **Done**.

### Option C — cleaner spoken times (optional)

If the whole-event reading is too verbose (reads the full date), replace step 3 with:
1. **Repeat with Each** (Calendar Events) →
2. inside: **Text** = `[Start Date]` (tap the Start Date chip → **Date: None, Time: Short**) + `, ` + `[Title]`
3. after repeat: **Combine Text** (Repeat Results, New Lines)
4. **Speak Text** the Combined Text.

---

## Speak it automatically when you start driving

Shortcuts → **Automation** → **+** → **Create Personal Automation**:

- **CarPlay → Connects → Run Shortcut → Today's Agenda** → turn **Ask Before Running OFF**.
- Add a second one: **Bluetooth → [your other car] → Connects → Run → Today's Agenda** (covers the non-CarPlay car).

Tips: put a **Wait** at the top of the shortcut (10s to let audio route, or **300s = 5 min** if you'd rather settle in first). Optionally wrap in **If (time 6–11 am)** so the full briefing only plays on morning drives. (Long background waits can occasionally be suspended by iOS; if so, just say "Hey Siri, Tara" instead.)

## Meeting reminders read aloud (no shortcut)

**Settings → Notifications → Announce Notifications → On →** enable **CarPlay** →
turn on **Calendar.** Siri now reads each meeting alert over the car speakers.
(Ensure events carry alerts: Settings → Calendar → Default Alert Times.)

## "Hey Tara" voice Q&A

You can't rename Siri's wake word, but you can name shortcuts so it feels close:
- Name one **`Tara`** → "Hey Siri, **Tara**" reads your agenda.
- `Today's Agenda` also responds to "Hey Siri, **what's today's agenda**".
- Add **`Next meeting`** (Find next event → Speak) and **`Am I free this afternoon`**
  for quick hands-free questions while driving.

For open-ended Q&A, a shortcut can POST your question + calendar to an LLM API —
later, optional.
