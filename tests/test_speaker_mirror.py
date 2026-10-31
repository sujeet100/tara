"""Tests for the speaker mirror's loudness — the volume keys only move the
Bluetooth headphones, so the built-in speakers sat at whatever level they were
last left (often full) and every mirrored line boomed into the room. The copy
must come out LOW, at the same loudness whatever the speakers' own slider says,
and must not follow headphones that are turned up to full."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import voice  # noqa: E402

FULL_PHONES = {"default_volume": 1.0, "builtin_volume": 1.0}


def test_default_is_low_even_with_headphones_at_full():
    assert voice.mirror_level({}, FULL_PHONES) == voice.DEFAULT_MIRROR_VOLUME


def test_target_is_absolute_whatever_the_speaker_slider():
    cfg = {"speaker_mirror": {"volume": 0.25}}
    half = {"default_volume": 1.0, "builtin_volume": 0.5}
    assert voice.mirror_level(cfg, half) * 0.5 == 0.25
    assert voice.mirror_level(cfg, FULL_PHONES) * 1.0 == 0.25


def test_speakers_below_target_cannot_be_boosted_past_full():
    route = {"default_volume": 1.0, "builtin_volume": 0.1}
    assert voice.mirror_level({"speaker_mirror": {"volume": 0.25}}, route) == 1.0


def test_unknown_speaker_slider_uses_target_as_is():
    assert voice.mirror_level({"speaker_mirror": {"volume": 0.3}}, {}) == 0.3
    muted = {"default_volume": 1.0, "builtin_volume": 0.0}
    assert voice.mirror_level({"speaker_mirror": {"volume": 0.3}}, muted) == 0.3


def test_system_follows_the_headphones_when_asked():
    route = {"default_volume": 0.3, "builtin_volume": 0.6}
    assert abs(voice.mirror_level({"speaker_mirror": {"volume": "system"}}, route) - 0.5) < 1e-9


def test_bad_settings_fall_back_to_the_low_default():
    assert voice.mirror_level({"speaker_mirror": {"volume": "loud"}}, FULL_PHONES) \
        == voice.DEFAULT_MIRROR_VOLUME
    assert voice.mirror_level({"speaker_mirror": {"volume": "system"}}, {}) \
        == voice.DEFAULT_MIRROR_VOLUME
    assert voice.mirror_level({"speaker_mirror": {"volume": 5}}, FULL_PHONES) == 1.0


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} passed")
