"""Tests for join detection — the logic that decides whether the user has actually
joined THIS meeting (so we can stand down) vs. some background app merely holding
the mic open (which must NOT stand down — that was the silent-failure bug)."""

import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import brain  # noqa: E402

TZ = ZoneInfo("Asia/Kolkata")
START = datetime(2026, 6, 2, 14, 0, tzinfo=TZ)   # a 2pm meeting
NOW = START - timedelta(minutes=1)                # one minute before


def jf(**kw):
    base = dict(ev_start=START, now=NOW, mic_active=False,
                mic_on_since=None, zoom_live=False, max_lead=5)
    base.update(kw)
    return brain.joined_for(**base)


def test_stuck_mic_is_not_a_join():
    # Slack held the mic open since this morning — must NOT read as joined.
    on_since = START - timedelta(hours=4)
    assert jf(mic_active=True, mic_on_since=on_since) is False


def test_recent_mic_is_a_join():
    # Mic went live 30s before the meeting — that's a real join.
    on_since = START - timedelta(seconds=30)
    assert jf(mic_active=True, mic_on_since=on_since) is True


def test_mic_just_inside_window_is_a_join():
    on_since = START - timedelta(minutes=6)  # within max_lead(5)+2 = 7 min
    assert jf(mic_active=True, mic_on_since=on_since) is True


def test_mic_off_is_not_a_join():
    assert jf(mic_active=False, mic_on_since=None) is False


def test_zoom_in_meeting_is_always_a_join():
    # CptHost present = genuinely in a Zoom call, regardless of mic timing.
    assert jf(zoom_live=True) is True


def test_recent_camera_is_a_join():
    # Video turned on near the meeting (mic stays off) — still a join.
    on_since = START - timedelta(seconds=20)
    assert jf(cam_active=True, cam_on_since=on_since) is True


def test_stuck_camera_is_not_a_join():
    # OBS / a stray tab held the camera open for hours — not a join.
    on_since = START - timedelta(hours=3)
    assert jf(cam_active=True, cam_on_since=on_since) is False


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} passed")
