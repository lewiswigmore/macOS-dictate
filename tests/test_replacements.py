from __future__ import annotations

from pathlib import Path

from dictate.replacements import apply, load


def test_load_replacements(tmp_path: Path) -> None:
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

    assert load(path) == {"kubernetic": "Kubernetes", "react js": "React"}


def test_apply_case_insensitive_whole_word_with_punctuation() -> None:
    table = {"kubernetic": "Kubernetes", "react": "React"}

    assert apply("Use kubernetic, then REACT.", table) == "Use Kubernetes, then React."


def test_apply_does_not_touch_substrings() -> None:
    assert apply("react reactor preact", {"react": "React"}) == "React reactor preact"
