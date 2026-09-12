"""Tests for the voice queue's sleep behaviour.

System sleep suspends a worker mid-playback, so every later worker piled up
behind a lock that would never be released and the whole backlog burst out on
wake — days of "I can't read your calendar" spoken at a Mac whose calendar was
by then fine. The queue must therefore be bounded at both points where it waits,
and must sweep up after workers that sleep killed outright."""

import fcntl
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import voice  # noqa: E402


def setup_queue(tmp: Path) -> None:
    voice.QUEUE_DIR = tmp / "voiceq"
    voice.LOCK_FILE = tmp / "voice.lock"
    voice.QUEUE_DIR.mkdir(parents=True, exist_ok=True)


def ticket(name: str, age_sec: float = 0) -> Path:
    t = voice.QUEUE_DIR / name
    t.write_text("line")
    if age_sec:
        stamp = time.time() - age_sec
        import os
        os.utime(t, (stamp, stamp))
    return t


def test_sweep_removes_orphans_but_keeps_live_tickets(tmp_path):
    setup_queue(tmp_path)
    old = ticket("00000000000000000001-111.ticket", age_sec=voice.TICKET_STALE_SEC + 60)
    fresh = ticket("00000000000000000002-222.ticket")
    voice.sweep_queue()
    assert not old.exists(), "a ticket whose worker sleep killed must be cleared"
    assert fresh.exists()


def test_wait_turn_gives_up_at_the_deadline(tmp_path):
    setup_queue(tmp_path)
    ticket("00000000000000000001-111.ticket")           # someone ahead of us, fresh
    mine = ticket("00000000000000000002-222.ticket")
    started = time.time()
    voice.wait_turn(mine, deadline=started + 0.5)
    assert time.time() - started < 3, "the queue wait must be bounded by the deadline"


def test_wait_turn_returns_at_once_when_nothing_is_ahead(tmp_path):
    setup_queue(tmp_path)
    mine = ticket("00000000000000000002-222.ticket")
    started = time.time()
    voice.wait_turn(mine, deadline=started + 30)
    assert time.time() - started < 1


def test_grab_lock_reports_failure_instead_of_blocking_forever(tmp_path):
    setup_queue(tmp_path)
    holder = open(voice.LOCK_FILE, "w")                  # a worker frozen by sleep
    fcntl.flock(holder, fcntl.LOCK_EX)
    try:
        with open(voice.LOCK_FILE, "w") as mine:
            started = time.time()
            held = voice.grab_lock(mine, deadline=started + 0.5)
        assert held is False, "a jammed holder must not stop us speaking"
        assert time.time() - started < 3
    finally:
        fcntl.flock(holder, fcntl.LOCK_UN)
        holder.close()


def test_grab_lock_succeeds_when_free(tmp_path):
    setup_queue(tmp_path)
    with open(voice.LOCK_FILE, "w") as mine:
        assert voice.grab_lock(mine, deadline=time.time() + 5) is True
        fcntl.flock(mine, fcntl.LOCK_UN)


if __name__ == "__main__":
    import shutil
    import tempfile
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        tmp = Path(tempfile.mkdtemp(prefix="ma_vq_"))
        try:
            fn(tmp)
            print(f"ok  {fn.__name__}")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n{len(fns)} passed")
