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

Flags (after the text argument):
  --soft    the user is on a call: speak like a person leaning in, not an
            announcer — quieter playback AND a gentler synthesis (lower pitch,
            slower rate, reduced volume), levels from config `in_call_voice`.
  --incall  a call is live but the soft register is disabled — playback is
            normal, but speaker mirroring is suppressed (see below) so nothing
            leaks into the room mid-meeting. --soft implies this.

Speaker mirroring: when the default output is a BLUETOOTH device and no call is
live, the same audio is also played on the built-in speakers (bin/audioroute).
Headphones that are connected but lying on the desk were silently swallowing
announcements — the exact failure mode this app exists to kill. Config
`speaker_mirror.enabled` turns it off.

Emoji are stripped before synthesis — '🌸 Standup' was being read as
'cherry blossom standup'.

Usage: voice.py "text to speak" [--soft|--incall]
       (reads tts / in_call_voice / speaker_mirror settings from config.json)
"""

from __future__ import annotations

import fcntl
import json
import logging
import os
import re
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
AUDIOROUTE_BIN = BASE / "bin" / "audioroute"

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

DEFAULT_SOFT = {
    "volume": 0.35,        # playback multiplier while he's on a call
    "edge_volume": "-40%",  # synthesize quieter too, not just play quieter
    "edge_rate": "-12%",    # slower —
    "edge_pitch": "-6Hz",   # — and lower: a person softening, not a dial turned down
    "edge_voice": "en-IN-NeerjaNeural",  # plain (non-Expressive) variant: no
}                                        # dramatic inflection mid-concentration

EMOJI_RE = re.compile(
    "["
    "\U0001F000-\U0001FAFF"   # the emoji planes: faces, hands, objects, symbols
    "\u2300-\u27BF"           # misc technical + dingbats (alarm clock, checkmark...)
    "\u2B00-\u2BFF"           # stars and heavy arrows
    "\uFE0E\uFE0F"            # variation selectors
    "\u200D"                  # zero-width joiner
    "\u20E3"                  # keycap combiner
    "]+")

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


def strip_emoji(text: str) -> str:
    """Drop emoji and tidy the spacing they leave behind."""
    return re.sub(r"\s{2,}", " ", EMOJI_RE.sub(" ", text)).strip()


def synthesize(text: str, tts: dict, soft: dict | None) -> Path | None:
    """Render text to an mp3 with edge-tts. None = use the `say` fallback."""
    if tts.get("engine", "edge") != "edge" or not EDGE_BIN.exists():
        return None
    fd, tmp = tempfile.mkstemp(prefix="ma_voice_", suffix=".mp3")
    os.close(fd)
    tmp_path = Path(tmp)
    rate = soft["edge_rate"] if soft else tts.get("edge_rate", DEFAULT_TTS["edge_rate"])
    voice_name = (soft.get("edge_voice") if soft else None) \
        or tts.get("edge_voice", DEFAULT_TTS["edge_voice"])
    cmd = [str(EDGE_BIN), "--voice", voice_name, f"--rate={rate}"]
    if soft:
        cmd += [f"--volume={soft['edge_volume']}", f"--pitch={soft['edge_pitch']}"]
    try:
        subprocess.run(cmd + ["--text", text, "--write-media", str(tmp_path)],
                       capture_output=True, timeout=SYNTH_TIMEOUT, check=True)
        if tmp_path.stat().st_size > 0:
            return tmp_path
    except Exception as exc:  # noqa: BLE001 (offline, timeout, bad voice — all → say)
        log.warning("edge synth failed (%s); falling back to say", type(exc).__name__)
    tmp_path.unlink(missing_ok=True)
    return None


def mirror_target(cfg: dict, in_call: bool) -> int | None:
    """Built-in speaker device id to mirror onto, or None.

    Mirror only when the default output is Bluetooth (headphones that may be on
    the desk rather than on the head) and no call is live — mid-call the voice
    must stay in his ear only, never leak into the room."""
    if in_call or not cfg.get("speaker_mirror", {}).get("enabled", True):
        return None
    if not AUDIOROUTE_BIN.exists():
        return None
    try:
        out = subprocess.run([str(AUDIOROUTE_BIN), "check"],
                             capture_output=True, text=True, timeout=5)
        info = json.loads(out.stdout)
    except Exception:  # noqa: BLE001
        return None
    if info.get("default_transport") != "bluetooth":
        return None
    builtin = info.get("builtin_id")
    return builtin if builtin and builtin != info.get("default_id") else None


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


def play(text: str, mp3: Path | None, tts: dict, soft: dict | None,
         mirror_device: int | None) -> None:
    """Play on the default output — and simultaneously on the built-in speakers
    when mirror_device is set, so idle headphones can't swallow the line."""
    procs = []
    if mp3 is not None:
        cmd = ["/usr/bin/afplay"]
        if soft:
            cmd += ["-v", str(soft["volume"])]
        procs.append(subprocess.Popen(cmd + [str(mp3)]))
        if mirror_device is not None:
            procs.append(subprocess.Popen(
                [str(AUDIOROUTE_BIN), "play", str(mp3),
                 "--device", str(mirror_device)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
    else:
        say_text = f"[[volm {soft['volume']}]] {text}" if soft else text
        rate = int(tts.get("say_rate", DEFAULT_TTS["say_rate"])) - (20 if soft else 0)
        cmd = ["/usr/bin/say",
               "-v", str(tts.get("say_voice", DEFAULT_TTS["say_voice"])),
               "-r", str(rate)]
        procs.append(subprocess.Popen(cmd + [say_text]))
        if mirror_device is not None:
            procs.append(subprocess.Popen(cmd + ["-a", str(mirror_device), say_text]))
    for p in procs:
        p.wait()


def main() -> None:
    argv = sys.argv[1:]
    soft_flag = "--soft" in argv
    in_call = soft_flag or "--incall" in argv
    text = strip_emoji(next((a for a in argv if not a.startswith("--")), "").strip())
    if not text:
        return
    setup_logging()
    cfg = load_config()
    tts = {**DEFAULT_TTS, **cfg.get("tts", {})}
    soft = {**DEFAULT_SOFT, **cfg.get("in_call_voice", {})} if soft_flag else None
    gap = float(cfg.get("voice_gap_sec", 1.5))
    mirror_device = mirror_target(cfg, in_call)

    QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    ticket = QUEUE_DIR / f"{time.time_ns():020d}-{os.getpid()}.ticket"
    ticket.write_text(text[:80])

    mp3 = None
    try:
        mp3 = synthesize(text, tts, soft)     # slow part, deliberately outside the queue
        wait_turn(ticket)
        with open(LOCK_FILE, "w") as lock:    # kernel releases on death — can't jam
            fcntl.flock(lock, fcntl.LOCK_EX)
            log.info("speaking (%s%s%s): %s", "edge" if mp3 else "say",
                     ", soft" if soft else "",
                     ", +speakers" if mirror_device else "", text)
            play(text, mp3, tts, soft, mirror_device)
            time.sleep(gap)                   # breath of silence before the next line
    finally:
        ticket.unlink(missing_ok=True)
        if mp3 is not None:
            mp3.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
