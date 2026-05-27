from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from dictate.logging_setup import get_logger

log = get_logger(__name__)

_SEPARATOR = "->"


@dataclass(frozen=True)
class Rule:
    """A single replacement rule.

    `pattern` is matched literally with word boundaries by default. When
    `regex=True`, `pattern` is compiled as a regular expression and
    `replacement` may use backreferences. Matching is case-insensitive
    unless `case_sensitive=True`.
    """

    pattern: str
    replacement: str
    regex: bool = False
    case_sensitive: bool = False
    source: str = field(default="", compare=False)

    def compiled(self) -> re.Pattern[str]:
        flags = 0 if self.case_sensitive else re.IGNORECASE
        if self.regex:
            return re.compile(self.pattern, flags)
        return re.compile(rf"(?<!\w){re.escape(self.pattern)}(?!\w)", flags)


def _rule_from_mapping(entry: dict[str, Any], src: str) -> Rule | None:
    pattern = entry.get("pattern") or entry.get("from")
    replacement = entry.get("replacement", entry.get("to", ""))
    if not pattern:
        log.warning("skipping replacement with empty pattern in %s", src)
        return None
    return Rule(
        pattern=str(pattern),
        replacement=str(replacement),
        regex=bool(entry.get("regex", False)),
        case_sensitive=bool(entry.get("case_sensitive", False)),
        source=src,
    )


def _load_yaml(path: Path) -> list[Rule]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    except yaml.YAMLError as exc:
        log.warning("failed to parse YAML replacements at %s: %s", path, exc)
        return []
    if not isinstance(raw, list):
        log.warning("replacements YAML at %s is not a list; ignoring", path)
        return []
    rules: list[Rule] = []
    for entry in raw:
        if isinstance(entry, dict):
            rule = _rule_from_mapping(entry, str(path))
            if rule is not None:
                rules.append(rule)
        else:
            log.warning("skipping non-mapping entry in %s", path)
    return rules


def _load_txt(path: Path) -> list[Rule]:
    rules: list[Rule] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        log.warning("failed to load replacements from %s: %s", path, exc)
        return rules
    for line_no, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if _SEPARATOR not in stripped:
            log.warning("skipping malformed replacement at %s:%d", path, line_no)
            continue
        source, target = (part.strip() for part in stripped.split(_SEPARATOR, 1))
        if not source or not target:
            log.warning("skipping empty replacement at %s:%d", path, line_no)
            continue
        rules.append(Rule(pattern=source, replacement=target, source=str(path)))
    return rules


def load(path: Path) -> list[Rule]:
    """Load rules from a single file. Format inferred from suffix."""
    if not path.exists():
        return []
    if path.suffix.lower() in {".yaml", ".yml"}:
        return _load_yaml(path)
    return _load_txt(path)


def load_layered(*paths: Path) -> list[Rule]:
    """Load and merge rules from multiple files. Later paths override earlier
    ones when patterns collide (case-insensitive literal match)."""
    merged: dict[str, Rule] = {}
    appended: list[Rule] = []
    for p in paths:
        for rule in load(p):
            if rule.regex:
                appended.append(rule)
                continue
            key = rule.pattern.lower()
            merged[key] = rule
    return list(merged.values()) + appended


def apply(text: str, rules: list[Rule] | dict[str, str]) -> str:
    """Apply replacement rules to text.

    Literal rules are applied in a single non-overlapping pass with longer
    patterns winning over shorter ones. Regex rules then run in order on the
    result. Accepts either a list of `Rule` objects or a legacy
    `{source: target}` dict for backward compatibility.
    """
    if not text:
        return text

    rule_list: list[Rule]
    if isinstance(rules, dict):
        rule_list = [Rule(pattern=k, replacement=v) for k, v in rules.items()]
    else:
        rule_list = list(rules)

    if not rule_list:
        return text

    literal = [r for r in rule_list if not r.regex]
    regex_rules = [r for r in rule_list if r.regex]
    literal.sort(key=lambda r: (-len(r.pattern), r.pattern.lower()))

    result = text
    if literal:
        ci_pattern = "|".join(
            rf"(?<!\w){re.escape(r.pattern)}(?!\w)" for r in literal if not r.case_sensitive
        )
        cs_pattern = "|".join(
            rf"(?<!\w){re.escape(r.pattern)}(?!\w)" for r in literal if r.case_sensitive
        )
        lookup_ci = {r.pattern.lower(): r.replacement for r in literal if not r.case_sensitive}
        lookup_cs = {r.pattern: r.replacement for r in literal if r.case_sensitive}
        if ci_pattern:
            result = re.sub(
                ci_pattern,
                lambda m: lookup_ci.get(m.group(0).lower(), m.group(0)),
                result,
                flags=re.IGNORECASE,
            )
        if cs_pattern:
            result = re.sub(cs_pattern, lambda m: lookup_cs.get(m.group(0), m.group(0)), result)

    for rule in regex_rules:
        try:
            result = rule.compiled().sub(rule.replacement, result)
        except re.error as exc:
            log.warning("bad regex in replacement '%s' (%s): %s", rule.pattern, rule.source, exc)
    return result
