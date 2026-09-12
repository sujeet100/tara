"""Tests for reminder_actions — which Apple Reminders deserve a voice line on a
given tick. The contract: a timed task speaks once as it comes due, follows up
once if still incomplete, and anything that came due ages ago (Mac asleep,
feature just enabled) is marked 'stale' silently — Tara must never open with a
barrage of ancient nags. Date-only tasks belong to the briefing, never here."""

import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import brain  # noqa: E402

TZ = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 7, 31, 16, 2, tzinfo=TZ)


def rem(rid, due_dt, has_time=True):
    return {"id": rid, "title": rid, "list": "Work", "has_time": has_time,
            "due": due_dt.isoformat() if has_time else due_dt.date().isoformat(),
            "due_dt": due_dt}


TIMESHEET = rem("timesheet", NOW - timedelta(minutes=2))
FUTURE = rem("send-report", NOW + timedelta(hours=1))
ANCIENT = rem("old-chore", NOW - timedelta(days=2))
DATE_ONLY = rem("someday", NOW - timedelta(hours=1), has_time=False)


def acts(rems, bucket=None, now=NOW):
    return [(r["id"], kind) for r, kind in
            brain.reminder_actions(rems, bucket if bucket is not None else {}, now)]


def key(r):
    return f"{r['id']}@{r['due']}"


def test_due_task_fires_once_it_comes_due():
    assert acts([TIMESHEET]) == [("timesheet", "due")]


def test_future_task_stays_quiet():
    assert acts([FUTURE]) == []


def test_date_only_task_never_fires_here():
    # it belongs to the morning briefing, not a midnight alarm
    assert acts([DATE_ONLY]) == []


def test_long_overdue_task_is_stale_not_spoken():
    assert acts([ANCIENT]) == [("old-chore", "stale")]


def test_announced_task_is_not_repeated():
    bucket = {key(TIMESHEET): {"announced": NOW.isoformat()}}
    assert acts([TIMESHEET], bucket) == []


def test_follow_up_after_the_wait():
    bucket = {key(TIMESHEET): {"announced": (NOW - timedelta(minutes=31)).isoformat()}}
    assert acts([TIMESHEET], bucket) == [("timesheet", "followup")]


def test_no_follow_up_before_the_wait():
    bucket = {key(TIMESHEET): {"announced": (NOW - timedelta(minutes=10)).isoformat()}}
    assert acts([TIMESHEET], bucket) == []


def test_stale_task_never_gets_a_follow_up():
    bucket = {key(ANCIENT): {"announced": (NOW - timedelta(hours=5)).isoformat(),
                             "stale": True}}
    assert acts([ANCIENT], bucket) == []


def test_followed_up_task_goes_silent_for_good():
    bucket = {key(TIMESHEET): {"announced": (NOW - timedelta(hours=2)).isoformat(),
                               "followed_up": (NOW - timedelta(hours=1)).isoformat()}}
    assert acts([TIMESHEET], bucket) == []


def test_recurring_next_occurrence_fires_fresh():
    # last week's occurrence is done and dusted; this week's has a new due key
    last_week = rem("timesheet", NOW - timedelta(days=7, minutes=2))
    bucket = {key(last_week): {"announced": "x", "followed_up": "y"}}
    assert acts([TIMESHEET], bucket) == [("timesheet", "due")]


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} passed")
