"""Tests for the voice worker's text cleanup — emoji in meeting titles and
reminder names ('🌸 Standup') were being read out loud ('cherry blossom
standup'). Words, times and punctuation must pass through untouched."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import voice  # noqa: E402


def test_emoji_are_dropped():
    assert voice.strip_emoji("🌸 Standup 🚀") == "Standup"


def test_mid_word_emoji_leaves_one_space():
    assert voice.strip_emoji("Sync📝notes") == "Sync notes"


def test_symbols_and_dingbats_go_too():
    assert voice.strip_emoji("⏰ Submit timesheet ✅⭐") == "Submit timesheet"


def test_plain_text_is_untouched():
    line = "Design review at 4:30 pm — don't be late, Sujit!"
    assert voice.strip_emoji(line) == line


def test_variation_selectors_and_joiners_vanish():
    assert voice.strip_emoji("On call 👨‍💻 today ☂️") == "On call today"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"\n{len(fns)} passed")
