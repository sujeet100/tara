"""Tests for the wrap-up warning — the voice-only nudge near the end of the
CURRENT meeting when another one follows soon. It must stay narrow: once per
meeting, only if he's actually in it, only when something genuinely follows —
otherwise it's noise, and noise trains him to ignore Tara."""

import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import brain  # noqa: E402

TZ = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 7, 3, 13, 56, tzinfo=TZ)
CFG = dict(brain.DEFAULT_CONFIG)

spoken: list[str] = []
brain.pick = lambda cat, cfg, **kw: f"{cat}:{kw.get('title')}"
brain.speak = lambda text, cfg: spoken.append(text)


def ev(key, start, end, partstat="ACCEPTED"):
    return {"key": key, "title": key, "start": start, "end": end,
            "url": "", "recurring": False, "partstat": partstat}


CURRENT = ev("standup", NOW - timedelta(minutes=26), NOW + timedelta(minutes=4))
SOON = ev("design-review", NOW + timedelta(minutes=6), NOW + timedelta(minutes=36))
FAR = ev("retro", NOW + timedelta(hours=3), NOW + timedelta(hours=4))
DECLINED = ev("skipme", NOW + timedelta(minutes=5), NOW + timedelta(minutes=30), "DECLINED")


def run(events, state=None, in_call=True, now=NOW):
    spoken.clear()
    state = state if state is not None else {}
    brain.maybe_wrapup(events, state, CFG, now, in_call=in_call)
    return state


def test_fires_when_next_meeting_is_soon():
    run([CURRENT, SOON])
    assert spoken == ["wrap_up:design-review"]


def test_fires_only_once_per_meeting():
    state = run([CURRENT, SOON])
    brain.maybe_wrapup([CURRENT, SOON], state, CFG,
                       NOW + timedelta(minutes=1), in_call=True)
    assert len(spoken) == 1


def test_silent_when_nothing_follows_soon():
    # overrunning is his call when the afternoon is clear
    run([CURRENT, FAR])
    assert spoken == []


def test_silent_when_he_never_joined():
    run([CURRENT, SOON], in_call=False)
    assert spoken == []


def test_acked_meeting_counts_as_joined():
    # he pressed "I'm in" earlier; devices may be off (muted room, notes-only)
    run([CURRENT, SOON], state={"acked": {"standup": "x"}}, in_call=False)
    assert spoken == ["wrap_up:design-review"]


def test_declined_followup_is_ignored():
    run([CURRENT, DECLINED])
    assert spoken == []


def test_quiet_while_plenty_of_time_remains():
    long_one = ev("longone", NOW - timedelta(minutes=10), NOW + timedelta(minutes=20))
    run([long_one, SOON])
    assert spoken == []


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} passed")
