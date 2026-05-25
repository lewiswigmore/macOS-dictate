from __future__ import annotations

from pathlib import Path

import pytest

from dictate.commands import CommandParser
from dictate.config import Config

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def parser() -> CommandParser:
    config = Config.load(REPO_ROOT)
    return CommandParser(config.commands)


def test_new_line(parser: CommandParser) -> None:
    cmd = parser.parse("new line")
    assert cmd is not None
    assert cmd.name == "new_line"
    assert cmd.action == "insert"
    assert cmd.text == "\n"


def test_new_line_strips_trailing_period(parser: CommandParser) -> None:
    cmd = parser.parse("new line.")
    assert cmd is not None
    assert cmd.name == "new_line"


def test_new_paragraph(parser: CommandParser) -> None:
    cmd = parser.parse("new paragraph")
    assert cmd is not None
    assert cmd.name == "new_paragraph"
    assert cmd.action == "insert"
    assert cmd.text == "\n\n"


def test_scratch_that(parser: CommandParser) -> None:
    parser.remember_inserted("hello")
    cmd = parser.parse("scratch that")
    assert cmd is not None
    assert cmd.name == "scratch_that"
    assert cmd.action == "scratch_last"
    assert cmd.count == 5


def test_spell_that(parser: CommandParser) -> None:
    cmd = parser.parse("spell that D I C")
    assert cmd is not None
    assert cmd.name == "spell_that"
    assert cmd.action == "insert"
    assert cmd.text == "DIC"


def test_spell_that_rejects_words(parser: CommandParser) -> None:
    assert parser.parse("spell that hello") is None


def test_paste_raw(parser: CommandParser) -> None:
    cmd = parser.parse("paste raw")
    assert cmd is not None
    assert cmd.name == "paste_raw"
    assert cmd.action == "paste_raw"


def test_no_partial_match(parser: CommandParser) -> None:
    assert parser.parse("I want a new line in the file") is None


def test_strips_whitespace(parser: CommandParser) -> None:
    cmd = parser.parse("  scratch that  ")
    assert cmd is not None
    assert cmd.name == "scratch_that"


def test_trailing_comma_stripped(parser: CommandParser) -> None:
    cmd = parser.parse("tab,")
    assert cmd is not None
    assert cmd.name == "tab"


def test_no_match_returns_none(parser: CommandParser) -> None:
    assert parser.parse("hello world how are you") is None


class TestBadRegexHandling:
    """Round-5 fix: a malformed regex in commands.yaml must NOT crash the
    pipeline; it should be logged and skipped, with other commands still
    functional."""

    def test_bad_pattern_is_skipped(self, caplog):
        commands = [
            {"name": "good", "action": "insert", "pattern": "hello", "text": "x"},
            {"name": "bad", "action": "insert", "pattern": "[unclosed", "text": "y"},
            {"name": "also_good", "action": "discard", "pattern": "scratch"},
        ]
        p = CommandParser(commands)

        import logging

        with caplog.at_level(logging.WARNING):
            # Good patterns still parse.
            assert p.parse("hello").name == "good"
            assert p.parse("scratch").name == "also_good"
            # No match for anything that would have required the bad pattern.
            assert p.parse("anything").name is None if p.parse("anything") else True

        # The bad pattern surfaced a warning naming the command + pattern.
        warnings = [r for r in caplog.records if r.levelname == "WARNING"]
        assert any("bad" in r.getMessage() and "[unclosed" in r.getMessage() for r in warnings)

    def test_no_crash_when_all_patterns_bad(self):
        commands = [
            {"name": "bad1", "action": "insert", "pattern": "[", "text": "x"},
            {"name": "bad2", "action": "insert", "pattern": "*", "text": "y"},
        ]
        p = CommandParser(commands)
        # Empty compile list ⇒ no match, no crash.
        assert p.parse("anything") is None
