"""Tests for the voice queue's sleep behaviour.

System sleep suspends a worker mid-playback, so every later worker piled up
behind a lock that would never be released and the whole backlog burst out on
wake — days of "I can't read your calendar" spoken at a Mac whose calendar was
by then fine. The queue must therefore be bounded at both points where it waits,
and must sweep up after workers that sleep killed outright."""

import fcntl
import os
import subprocess
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
        with open(voice.LOCK_FILE, "a+") as mine:
            started = time.time()
            held = voice.grab_lock(mine, deadline=started + 0.5)
        assert held is False, "the wait must end so the caller can drop the line"
        assert time.time() - started < 3
    finally:
        fcntl.flock(holder, fcntl.LOCK_UN)
        holder.close()


def spawn_holder(lock: Path, until_offset: float) -> subprocess.Popen:
    """A fake voice worker (its argv says voice.py, it leads its own session,
    as brain spawns them) that takes the lock and announces a playback budget
    ending `until_offset` seconds from now — negative = already overrun."""
    code = (
        "import fcntl, os, time\n"
        f"f = open({str(lock)!r}, 'a+'); fcntl.flock(f, fcntl.LOCK_EX)\n"
        f"f.seek(0); f.truncate(); f.write(f'{{os.getpid()}} {{time.time() + {until_offset}:.0f}}'); f.flush()\n"
        "print('ready', flush=True)\n"
        "time.sleep(60)\n")
    p = subprocess.Popen([sys.executable, "-c", code, "voice.py"],
                         stdout=subprocess.PIPE, text=True, start_new_session=True)
    p.stdout.readline()
    return p


def test_grab_lock_evicts_a_holder_past_its_budget(tmp_path):
    """The Oct 2026 bug: a hung speaker-mirror player kept its worker holding the
    lock for days, so every later line gave up waiting and played over the others.
    A holder past its own budget must be removed, and we take a proper turn."""
    setup_queue(tmp_path)
    holder = spawn_holder(voice.LOCK_FILE, until_offset=-(voice.JAM_GRACE_SEC + 60))
    orphan = ticket(f"00000000000000000001-{holder.pid}.ticket")
    try:
        with open(voice.LOCK_FILE, "a+") as mine:
            held = voice.grab_lock(mine, deadline=time.time() + 5)
            assert held is True, "a jammed holder must be evicted, not talked over"
            fcntl.flock(mine, fcntl.LOCK_UN)
        assert holder.wait(timeout=5) is not None
        assert not orphan.exists(), "the evicted worker's ticket must not block the queue"
    finally:
        holder.kill()


def test_grab_lock_never_talks_over_a_holder_mid_line(tmp_path):
    setup_queue(tmp_path)
    holder = spawn_holder(voice.LOCK_FILE, until_offset=60)
    try:
        with open(voice.LOCK_FILE, "a+") as mine:
            held = voice.grab_lock(mine, deadline=time.time() + 0.5)
        assert held is False, "a holder within its budget is waited for, not overlapped"
        assert holder.poll() is None, "and it must not be killed"
    finally:
        holder.kill()
        holder.wait()


def test_jammed_holder_ignores_a_leftover_record_when_the_lock_is_free(tmp_path):
    setup_queue(tmp_path)
    voice.LOCK_FILE.write_text(f"{os.getpid() + 1} {time.time() - 3600:.0f}")
    assert voice.jammed_holder() is None, "a stale record must never get a pid killed"


def test_wait_all_kills_a_player_that_overruns(tmp_path):
    hung = subprocess.Popen(["/bin/sleep", "30"])
    started = time.time()
    assert voice.wait_all([hung], deadline=started + 0.5) is False
    assert hung.poll() is not None, "a hung player must be killed, not waited on"
    assert time.time() - started < 3


def test_wait_all_reports_success_for_a_quick_player(tmp_path):
    quick = subprocess.Popen(["/usr/bin/true"])
    assert voice.wait_all([quick], deadline=time.time() + 5) is True


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
