from __future__ import annotations

import re
from collections.abc import Callable

from dictate.logging_setup import get_logger

log = get_logger(__name__)

_TRAILING_PUNCTUATION = re.compile(r"[.,!?]+\Z")
_WORD_PART = re.compile(r"[A-Za-z0-9]+")


def _case_words(words: list[str]) -> list[str]:
    parts: list[str] = []
    for word in words:
        parts.extend(part.lower() for part in _WORD_PART.findall(word))
    return parts


def _to_snake_case(words: list[str]) -> str:
    return "_".join(_case_words(words))


def _to_camel_case(words: list[str]) -> str:
    parts = _case_words(words)
    if not parts:
        return ""
    return parts[0] + "".join(part.capitalize() for part in parts[1:])


def _to_pascal_case(words: list[str]) -> str:
    return "".join(part.capitalize() for part in _case_words(words))


def _to_kebab_case(words: list[str]) -> str:
    return "-".join(_case_words(words))


def _to_screaming_snake(words: list[str]) -> str:
    return "_".join(_case_words(words)).upper()


CASE_TRIGGERS: dict[str, Callable[[list[str]], str]] = {
    "snake case": _to_snake_case,
    "camel case": _to_camel_case,
    "pascal case": _to_pascal_case,
    "kebab case": _to_kebab_case,
    "screaming snake": _to_screaming_snake,
}

SYMBOL_MAP = {
    "triple equals": "===",
    "double equals": "==",
    "not equals": "!=",
    "less or equal": "<=",
    "greater or equal": ">=",
    "less than": "<",
    "greater than": ">",
    "open paren": "(",
    "close paren": ")",
    "open bracket": "[",
    "close bracket": "]",
    "open brace": "{",
    "close brace": "}",
    "open angle": "<",
    "close angle": ">",
    "fat arrow": "=>",
    "double pipe": "||",
    "double ampersand": "&&",
    "at sign": "@",
    "new line": "\n",
    "single quote": "'",
    "equals": "=",
    "semicolon": ";",
    "colon": ":",
    "comma": ",",
    "dot": ".",
    "period": ".",
    "arrow": "->",
    "pipe": "|",
    "ampersand": "&",
    "underscore": "_",
    "dash": "-",
    "hyphen": "-",
    "plus": "+",
    "minus": "-",
    "star": "*",
    "asterisk": "*",
    "slash": "/",
    "backslash": "\\",
    "percent": "%",
    "hash": "#",
    "pound": "#",
    "dollar": "$",
    "caret": "^",
    "tilde": "~",
    "bang": "!",
    "exclamation": "!",
    "question": "?",
    "tab": "\t",
    "string": '"',
    "quote": '"',
    "apostrophe": "'",
    "backtick": "`",
}

_CASE_TRIGGER_WORDS = {
    trigger: trigger.split() for trigger in sorted(CASE_TRIGGERS, key=len, reverse=True)
}
_SYMBOL_TRIGGER_WORDS = [phrase.split() for phrase in sorted(SYMBOL_MAP, key=len, reverse=True)]


def _matches(words: list[str], start: int, phrase_words: list[str]) -> bool:
    return words[start : start + len(phrase_words)] == phrase_words


def _matches_any_case_trigger(words: list[str], start: int) -> bool:
    return any(
        _matches(words, start, phrase_words) for phrase_words in _CASE_TRIGGER_WORDS.values()
    )


def _matches_any_symbol_trigger(words: list[str], start: int) -> bool:
    return any(_matches(words, start, phrase_words) for phrase_words in _SYMBOL_TRIGGER_WORDS)


def _apply_case_triggers(text: str) -> str:
    raw_words = text.split()
    words = [word.lower() for word in raw_words]
    result: list[str] = []
    i = 0

    while i < len(raw_words):
        matched_trigger: tuple[str, list[str]] | None = None
        for trigger, phrase_words in _CASE_TRIGGER_WORDS.items():
            if _matches(words, i, phrase_words):
                matched_trigger = (trigger, phrase_words)
                break

        if matched_trigger is None:
            result.append(raw_words[i])
            i += 1
            continue

        trigger, phrase_words = matched_trigger
        start = i + len(phrase_words)
        j = start
        captured: list[str] = []
        while j < len(raw_words) and len(captured) < 5:
            if _matches_any_case_trigger(words, j) or _matches_any_symbol_trigger(words, j):
                break
            captured.append(raw_words[j])
            j += 1

        if len(captured) >= 2:
            converted = CASE_TRIGGERS[trigger](captured)
            if converted:
                result.append(converted)
                i = j
                continue

        result.extend(raw_words[i:start])
        i = start

    return " ".join(result)


def _apply_symbol_substitutions(text: str) -> str:
    result = text
    for source, target in sorted(SYMBOL_MAP.items(), key=lambda item: (-len(item[0]), item[0])):
        pattern = re.compile(rf"(?<!\w){re.escape(source)}(?!\w)", re.IGNORECASE)
        result = pattern.sub(lambda _match, replacement=target: replacement, result)
    return result


def transform(text: str) -> str:
    """Apply code-grammar transformations to dictated text."""
    stripped = _TRAILING_PUNCTUATION.sub("", text.strip())
    if not stripped:
        return ""
    converted = _apply_case_triggers(stripped)
    return _apply_symbol_substitutions(converted)
