"""Anti-evasion detection and normalization module.

Catches zero-width/hidden characters, homoglyphs (Cyrillic/Greek lookalikes),
mixed-script evasion words, and artificially spaced text runs.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

# Zero-width, formatting, and invisible characters commonly used to break shingles
ZERO_WIDTH_CHARS = {
    0x200B: None,  # Zero Width Space
    0x200C: None,  # Zero Width Non-Joiner
    0x200D: None,  # Zero Width Joiner
    0x2060: None,  # Word Joiner
    0xFEFF: None,  # Zero Width No-Break Space (BOM)
    0x00AD: None,  # Soft Hyphen
    0x200E: None,  # Left-to-Right Mark
    0x200F: None,  # Right-to-Left Mark
}

# Homoglyph lookalike mapping (Cyrillic and Greek -> Latin)
HOMOGLYPH_MAP = {
    # Lowercase Cyrillic
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "х": "x", "у": "y", "і": "i",
    "ј": "j", "ѕ": "s", "ԁ": "d", "ԛ": "q", "ԝ": "w",
    # Uppercase Cyrillic
    "А": "A", "В": "B", "Е": "E", "К": "K", "М": "M", "Н": "H", "О": "O", "Р": "P",
    "С": "C", "Т": "T", "Х": "X", "І": "I", "Ј": "J", "Ѕ": "S",
    # Greek
    "α": "a", "ο": "o", "ν": "v", "ρ": "p", "κ": "k", "τ": "t",
    "Α": "A", "Β": "B", "Ε": "E", "Η": "H", "Ι": "I", "Κ": "K", "Μ": "M", "Ν": "N",
    "Ο": "O", "Ρ": "P", "Τ": "T", "Χ": "X", "Υ": "Y", "Ζ": "Z",
}

# Regex to detect spaced single letters like: 'p l a g i a r i s m'
SPACED_LETTERS_PATTERN = re.compile(r"(?:\b[a-zA-Z]\b\s+){6,}\b[a-zA-Z]\b")


@dataclass
class EvasionResult:
    cleaned_text: str
    flags: list[str] = field(default_factory=list)
    zero_width_count: int = 0
    homoglyphs_fixed: int = 0
    spaced_runs_count: int = 0


def detect_and_clean_evasion(text: str) -> EvasionResult:
    """Analyze and clean evasion attempts in submitted text.
    
    Returns EvasionResult containing the sanitized text and audit flags.
    """
    flags: list[str] = []

    # 1. Zero-width character detection & removal
    zw_count = sum(1 for ch in text if ord(ch) in ZERO_WIDTH_CHARS)
    if zw_count > 0:
        flags.append(f"{zw_count} hidden/zero-width characters detected and removed")
        text = text.translate(ZERO_WIDTH_CHARS)

    # 2. Unicode NFKC normalization
    text = unicodedata.normalize("NFKC", text)

    # 3. Homoglyph / Mixed script detection
    homoglyphs_fixed = 0

    def replace_homoglyphs_in_word(match: re.Match) -> str:
        nonlocal homoglyphs_fixed
        word = match.group()
        # Check if the word contains a mix of standard Latin and lookalikes
        has_latin = any(("a" <= c.lower() <= "z") for c in word)
        has_lookalike = any(c in HOMOGLYPH_MAP for c in word)

        if has_lookalike and (has_latin or len(word) > 2):
            replaced = []
            for ch in word:
                if ch in HOMOGLYPH_MAP:
                    replaced.append(HOMOGLYPH_MAP[ch])
                    homoglyphs_fixed += 1
                else:
                    replaced.append(ch)
            return "".join(replaced)
        return word

    text = re.sub(r"\w+", replace_homoglyphs_in_word, text)
    if homoglyphs_fixed > 0:
        flags.append(
            f"{homoglyphs_fixed} homoglyphic characters (mixed Cyrillic/Greek lookalikes) normalized to Latin"
        )

    # 4. Spaced letter runs detection
    spaced_runs = SPACED_LETTERS_PATTERN.findall(text)
    spaced_count = len(spaced_runs)
    if spaced_count > 0:
        flags.append(
            f"{spaced_count} instances of letter-spaced evasion (e.g. 'e v a s i o n') detected"
        )
        # Collapse artificially spaced letters
        def collapse_spaces(match: re.Match) -> str:
            return re.sub(r"\s+", "", match.group())

        text = SPACED_LETTERS_PATTERN.sub(collapse_spaces, text)

    return EvasionResult(
        cleaned_text=text,
        flags=flags,
        zero_width_count=zw_count,
        homoglyphs_fixed=homoglyphs_fixed,
        spaced_runs_count=spaced_count,
    )
