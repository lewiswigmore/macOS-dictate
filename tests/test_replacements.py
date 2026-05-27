from __future__ import annotations

from pathlib import Path

from dictate.replacements import Rule, apply, load, load_layered


def test_load_txt_legacy(tmp_path: Path) -> None:
    path = tmp_path / "replacements.txt"
    path.write_text(
        "\n".join(
            [
                "# comment",
                "kubernetic -> Kubernetes",
                "react js -> React",
                "",
            ]
        ),
        encoding="utf-8",
    )

    rules = load(path)
    patterns = {r.pattern: r.replacement for r in rules}
    assert patterns == {"kubernetic": "Kubernetes", "react js": "React"}
    assert all(r.regex is False for r in rules)


def test_load_yaml(tmp_path: Path) -> None:
    path = tmp_path / "replacements.yaml"
    path.write_text(
        """
- pattern: kubernetic
  replacement: Kubernetes
- pattern: open ai
  replacement: OpenAI
- pattern: "next ?js"
  replacement: Next.js
  regex: true
""",
        encoding="utf-8",
    )
    rules = load(path)
    assert [r.pattern for r in rules] == ["kubernetic", "open ai", "next ?js"]
    assert rules[2].regex is True


def test_load_missing_returns_empty(tmp_path: Path) -> None:
    assert load(tmp_path / "missing.yaml") == []
    assert load(tmp_path / "missing.txt") == []


def test_apply_case_insensitive_whole_word_with_punctuation() -> None:
    rules = [
        Rule(pattern="kubernetic", replacement="Kubernetes"),
        Rule(pattern="react", replacement="React"),
    ]
    assert apply("Use kubernetic, then REACT.", rules) == "Use Kubernetes, then React."


def test_apply_does_not_touch_substrings() -> None:
    rules = [Rule(pattern="react", replacement="React")]
    assert apply("react reactor preact", rules) == "React reactor preact"


def test_apply_legacy_dict_input() -> None:
    assert apply("kubernetic", {"kubernetic": "Kubernetes"}) == "Kubernetes"


def test_apply_regex_with_backreference() -> None:
    rules = [Rule(pattern=r"v(\d+)\.(\d+)", replacement=r"version \1 dot \2", regex=True)]
    assert apply("running v3.12 now", rules) == "running version 3 dot 12 now"


def test_apply_case_sensitive_rule() -> None:
    rules = [Rule(pattern="API", replacement="API", case_sensitive=True)]
    # case-sensitive rule should not touch the lowercase token
    assert apply("the api call", rules) == "the api call"


def test_apply_bad_regex_does_not_crash() -> None:
    rules = [Rule(pattern="(unbalanced", replacement="x", regex=True)]
    assert apply("hello", rules) == "hello"


def test_load_layered_merges_with_preset_override(tmp_path: Path) -> None:
    global_path = tmp_path / "replacements.yaml"
    global_path.write_text(
        "- pattern: api\n  replacement: API\n- pattern: js\n  replacement: JavaScript\n",
        encoding="utf-8",
    )
    preset_path = tmp_path / "code.replacements.yaml"
    preset_path.write_text(
        "- pattern: js\n  replacement: JS\n",
        encoding="utf-8",
    )
    rules = load_layered(global_path, preset_path)
    by_pattern = {r.pattern.lower(): r.replacement for r in rules}
    assert by_pattern == {"api": "API", "js": "JS"}


def test_load_layered_keeps_regex_rules_from_all_files(tmp_path: Path) -> None:
    a = tmp_path / "a.yaml"
    a.write_text("- pattern: 'a+'\n  replacement: A\n  regex: true\n", encoding="utf-8")
    b = tmp_path / "b.yaml"
    b.write_text("- pattern: 'b+'\n  replacement: B\n  regex: true\n", encoding="utf-8")
    rules = load_layered(a, b)
    assert sum(1 for r in rules if r.regex) == 2


def test_apply_longest_literal_wins() -> None:
    rules = [
        Rule(pattern="vs", replacement="versus"),
        Rule(pattern="vs code", replacement="VS Code"),
    ]
    assert apply("open vs code now", rules) == "open VS Code now"
