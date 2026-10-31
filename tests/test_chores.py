"""Tests for scheduled chores — the Friday timesheet and anything like it.

A chore is the one thing Tara escalates all the way to taking the screen, so the
ladder has to be exact in both directions. Too eager and she blocks a screen he
was using properly, which teaches him to kill the process; too slow and the thing
she exists to prevent happens anyway. The block is also a GATE: opening the link
stands her down for a grace period, because blocking a screen he then can't work
on would be theatre rather than help."""

import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import brain  # noqa: E402

TZ = ZoneInfo("Asia/Kolkata")
FRIDAY = datetime(2026, 9, 18, 10, 0, tzinfo=TZ)     # a Friday, 10:00
CHORE = {"id": "timesheet", "title": "Submit your timesheet", "weekday": "friday",
         "time": "10:00", "url": "https://sadhak.sahaj.ai/timetracker/timesheet",
         "cta": "Open Sadhak", "nag_every_min": 15, "block_after_min": 45,
         "grace_min": 10}
LADDER = dict(nag_every_min=15, block_after_min=45)


def plan(minutes_over, rec=None):
    return brain.chore_plan(FRIDAY, FRIDAY + timedelta(minutes=minutes_over),
                            rec or {}, **LADDER)


def test_it_only_fires_on_its_own_weekday():
    for day, expect in ((16, None), (17, None), (18, "due"), (19, None)):
        now = datetime(2026, 9, day, 10, 30, tzinfo=TZ)
        got = brain.chore_due_at(CHORE, now)
        assert (got is not None) == (expect == "due"), f"2026-09-{day}: {got}"


def test_due_time_is_todays_clock_time():
    assert brain.chore_due_at(CHORE, FRIDAY + timedelta(hours=4)) == FRIDAY


def test_a_malformed_chore_is_ignored_rather_than_crashing():
    assert brain.chore_due_at({"weekday": "someday", "time": "10:00"}, FRIDAY) is None
    assert brain.chore_due_at({"weekday": "friday", "time": "not-a-time"}, FRIDAY) is None


def test_nothing_happens_before_it_is_due():
    assert plan(-5) == (False, None)


def test_the_ladder_climbs_gentle_firm_upset_then_blocks():
    assert plan(0) == (False, "chore_due")
    assert plan(15) == (False, "chore_firm")
    assert plan(30) == (False, "chore_upset")
    assert plan(45) == (True, "chore_blocked")


def test_she_stays_quiet_between_rungs():
    spoken_at = (FRIDAY + timedelta(minutes=15)).isoformat()
    assert plan(16, {"spoke": spoken_at}) == (False, None), "one line per rung, not per tick"
    assert plan(30, {"spoke": spoken_at}) == (False, "chore_upset")


def test_the_block_persists_even_on_a_silent_tick():
    recent = (FRIDAY + timedelta(minutes=45)).isoformat()
    should_block, category = plan(46, {"spoke": recent})
    assert should_block is True, "the screen stays blocked between spoken lines"
    assert category is None, "but she doesn't repeat herself every 60 seconds"


def test_half_a_tick_of_slack_so_a_60s_tick_cannot_skip_a_rung():
    spoken_at = FRIDAY.isoformat()
    assert plan(14.6, {"spoke": spoken_at}) == (False, "chore_firm")


def test_a_lid_opened_late_lands_where_she_would_have_got_to():
    # Mac asleep all morning, opened at 14:00 — four hours overdue is a block,
    # not a fresh 'gentle' nudge starting the ladder over.
    should_block, category = plan(240)
    assert should_block is True
    assert category == "chore_blocked"


# --------------------------------------------------------------------------- #
# maybe_chores — the parts with a screen attached
# --------------------------------------------------------------------------- #
CFG = {**brain.DEFAULT_CONFIG, "chores": [CHORE], "name": "Sujit",
       "work_hours": {"start": "08:00", "end": "21:00"}}

spoken: list[str] = []
launched: list[tuple] = []
killed: list[int] = []
ALIVE: set[int] = set()
CHOICE: dict[str, str] = {}

brain.pick = lambda cat, cfg, **kw: cat
brain.speak = lambda text, cfg, in_call=False: spoken.append(text)
brain.show_toast = lambda *a, **k: None
brain.pid_alive = lambda pid: pid in ALIVE
brain.kill_overlay = lambda pid: killed.append(pid) if pid else None
brain.read_choice = lambda sid: CHOICE.pop(sid, None)


def fake_launch(safe_id, title, start_iso, url, **kw):
    launched.append((kw.get("mode"), title, url, kw.get("cta")))
    pid = 2000 + len(launched)
    ALIVE.add(pid)
    return pid


brain.launch_overlay = fake_launch


def fresh():
    spoken.clear(); launched.clear(); killed.clear(); ALIVE.clear(); CHOICE.clear()
    return {}


def run(state, minutes_over, in_call=False):
    brain.maybe_chores(state, CFG, FRIDAY + timedelta(minutes=minutes_over), in_call)


def test_block_goes_up_once_the_ladder_runs_out():
    st = fresh()
    run(st, 0);  assert spoken == ["chore_due"] and launched == []
    run(st, 15); run(st, 30)
    assert spoken == ["chore_due", "chore_firm", "chore_upset"], spoken
    assert launched == [], "she talks first — the screen is the last resort"
    run(st, 45)
    assert launched == [("chore", "Submit your timesheet", CHORE["url"], "Open Sadhak")]
    assert spoken[-1] == "chore_blocked"


def test_opening_the_link_stands_her_down_so_the_work_is_possible():
    st = fresh()
    run(st, 45)
    assert len(launched) == 1
    sid = brain.safe_id(f"timesheet@{FRIDAY.date().isoformat()}")
    CHOICE[sid] = "open"                      # he pressed "Open Sadhak"
    run(st, 46)
    assert killed, "the block must get out of the way of the page it just opened"
    assert len(launched) == 1, "and must not come straight back"
    run(st, 50)
    assert len(launched) == 1, "still inside the 10-minute grace"
    ALIVE.clear()                             # the window is gone
    run(st, 57)                               # grace expired, still not submitted
    assert len(launched) == 2, "if nothing was submitted, she comes back"


def test_saying_it_is_done_ends_it_for_the_day():
    st = fresh()
    run(st, 45)
    sid = brain.safe_id(f"timesheet@{FRIDAY.date().isoformat()}")
    CHOICE[sid] = "ack"
    run(st, 46)
    assert killed, "the block comes down on ack"
    before = len(spoken)
    ALIVE.clear()
    run(st, 120); run(st, 300)
    assert len(launched) == 1 and len(spoken) == before, "acked means acked"


def test_a_live_meeting_outranks_the_block():
    st = fresh()
    st["overlay"] = {"some-meeting": {"pid": 999}}
    ALIVE.add(999)
    run(st, 45)
    assert launched == [], "never take the screen out from under a meeting"
    assert spoken[-1] == "chore_blocked", "she still says it out loud"
    ALIVE.discard(999)                        # meeting over
    run(st, 60)
    assert len(launched) == 1, "the block lands the moment he's free"


def test_nothing_outside_work_hours():
    st = fresh()
    run(st, 12 * 60)                          # 22:00 — past work_hours end
    assert spoken == [] and launched == []


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} passed")
