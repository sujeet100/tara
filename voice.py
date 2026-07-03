#!/usr/bin/env python3
"""Voice worker — speaks ONE line, serialized against every other voice worker.

brain.py's speak() spawns one detached instance of this per utterance so the
per-minute tick never blocks on audio. Without serialization, two announcements
landing on the same tick (morning briefing + a lead alert, or two meetings
starting together) played simultaneously — two voices talking over each other.

The fix, in three steps per worker:

1. SYNTHESIZE first, before queueing. edge-tts is a network call with variable
   latency; doing it up front means workers overlap on the slow part and the
   queue only serializes actual playback. Offline/failed synth falls back to
   macOS `say` so a reminder is never lost (same guarantee as before).
2. WAIT MY TURN via a ticket file in runtime/voiceq/ (named by nanosecond
   timestamp, so ticks' call order is preserved). Tickets older than
   TICKET_STALE_SEC are ignored — a crashed worker can't jam the queue.
3. PLAY holding an exclusive flock on runtime/voice.lock, then keep it for
   `voice_gap_sec` more so consecutive announcements get a breath of silence
   between them. The kernel drops the lock if we die, so no stale-lock state.

Usage: voice.py "text to speak"   (reads tts settings from config.json)
"""

from __future__ import annotations

import fcntl
import json
import logging
import os
import subprocess
import sys
import tempfile
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

BASE = Path.home() / ".meeting-assistant"
RUNTIME = BASE / "runtime"
QUEUE_DIR = RUNTIME / "voiceq"
LOCK_FILE = RUNTIME / "voice.lock"
CONFIG_FILE = BASE / "config.json"
EDGE_BIN = BASE / "venv" / "bin" / "edge-tts"

TICKET_STALE_SEC = 300   # a ticket this old means its worker died — ignore it
WAIT_TURN_TIMEOUT = 240  # never wait longer than this for the queue (fail loud > fail mute)
SYNTH_TIMEOUT = 30       # edge-tts network budget before falling back to `say`

DEFAULT_TTS = {
    "engine": "edge",
    "edge_voice": "en-IN-NeerjaExpressiveNeural",
    "edge_rate": "-3%",
    "say_voice": "Tara",
    "say_rate": 175,
}

log = logging.getLogger("voice")


def setup_logging() -> None:
    logs = BASE / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(logs / "voice.log", maxBytes=500_000, backupCount=2)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(handler)
    log.setLevel(logging.INFO)


def load_config() -> dict:
    try:
        return json.loads(CONFIG_FILE.read_text())
    except Exception:  # noqa: BLE001
        return {}


def synthesize(text: str, tts: dict) -> Path | None:
    """Render text to an mp3 with edge-tts. None = use the `say` fallback."""
    if tts.get("engine", "edge") != "edge" or not EDGE_BIN.exists():
        return None
    fd, tmp = tempfile.mkstemp(prefix="ma_voice_", suffix=".mp3")
    os.close(fd)
    tmp_path = Path(tmp)
    try:
        subprocess.run(
            [str(EDGE_BIN),
             "--voice", tts.get("edge_voice", DEFAULT_TTS["edge_voice"]),
             f"--rate={tts.get('edge_rate', DEFAULT_TTS['edge_rate'])}",
             "--text", text, "--write-media", str(tmp_path)],
            capture_output=True, timeout=SYNTH_TIMEOUT, check=True)
        if tmp_path.stat().st_size > 0:
            return tmp_path
    except Exception as exc:  # noqa: BLE001 (offline, timeout, bad voice — all → say)
        log.warning("edge synth failed (%s); falling back to say", type(exc).__name__)
    tmp_path.unlink(missing_ok=True)
    return None


def wait_turn(my_ticket: Path) -> None:
    """Block until no fresh ticket is ahead of us (FIFO by nanosecond name)."""
    deadline = time.time() + WAIT_TURN_TIMEOUT
    while time.time() < deadline:
        ahead = [t for t in QUEUE_DIR.glob("*.ticket")
                 if t.name < my_ticket.name
                 and time.time() - t.stat().st_mtime < TICKET_STALE_SEC]
        if not ahead:
            return
        time.sleep(0.25)
    log.warning("queue wait timed out; speaking anyway")


def play(text: str, mp3: Path | None, tts: dict) -> None:
    if mp3 is not None:
        subprocess.run(["/usr/bin/afplay", str(mp3)], check=False)
    else:
        subprocess.run(["/usr/bin/say",
                        "-v", str(tts.get("say_voice", DEFAULT_TTS["say_voice"])),
                        "-r", str(tts.get("say_rate", DEFAULT_TTS["say_rate"])),
                        text], check=False)


def main() -> None:
    text = sys.argv[1].strip() if len(sys.argv) > 1 else ""
    if not text:
        return
    setup_logging()
    cfg = load_config()
    tts = {**DEFAULT_TTS, **cfg.get("tts", {})}
    gap = float(cfg.get("voice_gap_sec", 1.5))

    QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    ticket = QUEUE_DIR / f"{time.time_ns():020d}-{os.getpid()}.ticket"
    ticket.write_text(text[:80])

    mp3 = None
    try:
        mp3 = synthesize(text, tts)          # slow part, deliberately outside the queue
        wait_turn(ticket)
        with open(LOCK_FILE, "w") as lock:   # kernel releases on death — can't jam
            fcntl.flock(lock, fcntl.LOCK_EX)
            log.info("speaking (%s): %s", "edge" if mp3 else "say", text)
            play(text, mp3, tts)
            time.sleep(gap)                  # breath of silence before the next line
    finally:
        ticket.unlink(missing_ok=True)
        if mp3 is not None:
            mp3.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
