"""Test caption word-wrapping (regression for issue #1).

Latin captions must NOT break mid-word. CJK input has no spaces, so it must
continue to fall through to per-character greedy fill (existing V0.2 behavior).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from PIL import ImageFont  # noqa: E402

from title_card import _resolve_font, _wrap_caption  # noqa: E402


def _font(weight: str = "bold", size: int = 60) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(_resolve_font(weight)), size)


# Real director-pipeline captions (issue #1 table)
LATIN_CAPTIONS = [
    "STOP. You're doing it wrong.",
    "Faster than a .22 bullet",
    "1500 N - 2500x body weight",
    "The commute is hers",
    "Step 4: Backs of hands",
]


def test_latin_no_mid_word_break() -> None:
    """Every word in every wrapped line must be a complete word from the original.

    Use a narrow max_width to force wrapping on short captions.
    """
    font = _font("bold", size=60)
    # 600 px is narrow enough that 2-3 line wraps are forced for these captions.
    max_w = 600
    for cap in LATIN_CAPTIONS:
        lines = _wrap_caption(cap, font, max_w)
        assert lines, f"empty wrap result for {cap!r}"
        original_words = set(cap.split())
        for line in lines:
            for word in line.split():
                assert word in original_words, (
                    f"mid-word break detected: caption={cap!r} → lines={lines!r}; "
                    f"line={line!r} contains fragment {word!r} not in original "
                    f"words {sorted(original_words)!r}"
                )
    print("ok: no Latin mid-word break")


def test_cjk_char_split_preserved() -> None:
    """CJK has no spaces — must continue char-level wrapping with no char loss."""
    font = _font("bold", size=60)
    max_w = 200
    for cap in ["牙齿王国", "把光留在水面"]:
        lines = _wrap_caption(cap, font, max_w)
        assert lines, f"empty CJK wrap for {cap!r}"
        joined = "".join(lines)
        assert joined == cap, (
            f"CJK char loss: input={cap!r}, output={lines!r} (joined={joined!r})"
        )
    print("ok: CJK char-split preserved")


def test_explicit_newline_creates_break() -> None:
    """Explicit \\n in caption text forces a line break (preserve V0.2 behavior)."""
    font = _font("bold", size=60)
    lines = _wrap_caption("Line1\nLine2", font, 1000)
    assert lines == ["Line1", "Line2"], (
        f"explicit \\n not honored: got {lines!r}"
    )
    print("ok: explicit \\n preserved")


def test_oversized_token_falls_back_to_char_split() -> None:
    """A single Latin token wider than max_width must char-split (graceful).

    Real-world: a long URL or made-up word in narrow column.
    """
    font = _font("bold", size=60)
    long_word = "supercalifragilisticexpialidocious"
    lines = _wrap_caption(long_word, font, 200)
    assert lines, "empty result for oversized token"
    joined = "".join(lines)
    assert joined == long_word, (
        f"char loss in oversized-token fallback: input={long_word!r}, "
        f"output={lines!r}, joined={joined!r}"
    )
    print("ok: oversized-token char-split fallback")


def test_short_caption_single_line() -> None:
    """Short caption that fits comfortably must stay one line."""
    font = _font("bold", size=60)
    lines = _wrap_caption("Hello", font, 1000)
    assert lines == ["Hello"], f"short caption mishandled: {lines!r}"
    print("ok: short caption stays single line")


def test_empty_input_returns_empty() -> None:
    font = _font("bold", size=60)
    assert _wrap_caption("", font, 1000) == []
    print("ok: empty input → empty list")


def main() -> int:
    test_latin_no_mid_word_break()
    test_cjk_char_split_preserved()
    test_explicit_newline_creates_break()
    test_oversized_token_falls_back_to_char_split()
    test_short_caption_single_line()
    test_empty_input_returns_empty()
    print("all wrap tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
