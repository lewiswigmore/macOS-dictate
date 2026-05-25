"""Lightweight rule-based punctuation + casing pass.

Runs in <1 ms with zero dependencies. Used to polish raw ASR output when the
LLM cleanup step is skipped (Fast Mode or short utterances). Bridges the
quality gap between raw whisper and a full LLM rewrite, without the latency.

Deliberately conservative — only fixes obviously-wrong things. Anything
ambiguous is left alone so we don't introduce *new* errors.
"""

from __future__ import annotations

import re

# Common "I" contractions whisper sometimes lowercases.
_I_CONTRACTIONS = ("i'm", "i've", "i'll", "i'd")

# Tokens that should never be terminated with a period (interjections, etc.)
_TERMINAL_PUNCT = ".!?…"

# Match a standalone lowercase "i" surrounded by word boundaries.
_LONE_I_RE = re.compile(r"\bi\b")

# Match "i" followed by a contraction apostrophe.
_I_CONTRACTION_RE = re.compile(r"\bi(?=['\u2019](m|ve|ll|d)\b)", flags=re.IGNORECASE)

# Filler words to optionally strip when surrounded by whitespace.
# Disabled by default — many people deliberately dictate fillers.
_FILLER_RE = re.compile(r"\b(um|uh|erm|hmm)\b[,]?\s*", flags=re.IGNORECASE)


def smart_punctuate(text: str, *, strip_fillers: bool = False) -> str:
    """Return a cleaned-up version of ``text``.

    Rules applied (in order):
        1. Strip surrounding whitespace and collapse internal double-spaces.
        2. Optionally remove filler words ("um", "uh", ...).
        3. Capitalize the very first alphabetic character.
        4. Capitalize standalone "i" → "I", including "i'm/'ve/'ll/'d".
        5. Append "." if the result doesn't already end in terminal punctuation.

    Idempotent — running it twice yields the same result.
    """
    if not text:
        return text

    s = text.strip()
    if not s:
        return s

    s = re.sub(r"[ \t]{2,}", " ", s)

    if strip_fillers:
        s = _FILLER_RE.sub("", s).strip()
        s = re.sub(r"[ \t]{2,}", " ", s)
        if not s:
            return s

    s = _I_CONTRACTION_RE.sub("I", s)
    s = _LONE_I_RE.sub("I", s)

    # Capitalize the first alphabetic char (skip leading quotes / brackets).
    for idx, ch in enumerate(s):
        if ch.isalpha():
            if ch.islower():
                s = s[:idx] + ch.upper() + s[idx + 1 :]
            break

    if s[-1] not in _TERMINAL_PUNCT:
        s += "."

    return s
