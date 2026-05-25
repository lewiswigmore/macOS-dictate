from __future__ import annotations

from pathlib import Path

from dictate.config import Config
from dictate.vocab import as_initial_prompt, load_vocab


def _make_config(root: Path) -> Config:
    (root / "config" / "vocab" / "projects").mkdir(parents=True)
    return Config(root=root)


def test_code_preset_includes_code_txt(tmp_path: Path) -> None:
    root = tmp_path
    (root / "config" / "vocab" / "projects").mkdir(parents=True)
    (root / "config" / "vocab" / "code.txt").write_text("pytest\nmypy\n")
    (root / "config" / "vocab" / "work.txt").write_text("")
    (root / "config" / "vocab" / "personal.txt").write_text("")
    config = Config(root=root)
    terms = load_vocab(config, preset="code")
    assert "pytest" in terms
    assert "mypy" in terms


def test_non_code_preset_excludes_code_txt(tmp_path: Path) -> None:
    root = tmp_path
    (root / "config" / "vocab" / "projects").mkdir(parents=True)
    (root / "config" / "vocab" / "code.txt").write_text("pytest\n")
    (root / "config" / "vocab" / "work.txt").write_text("")
    (root / "config" / "vocab" / "personal.txt").write_text("")
    config = Config(root=root)
    terms = load_vocab(config, preset="default")
    assert "pytest" not in terms


def test_work_and_personal_always_included(tmp_path: Path) -> None:
    root = tmp_path
    (root / "config" / "vocab" / "projects").mkdir(parents=True)
    (root / "config" / "vocab" / "code.txt").write_text("")
    (root / "config" / "vocab" / "work.txt").write_text("Acme\n")
    (root / "config" / "vocab" / "personal.txt").write_text("Alice\n")
    config = Config(root=root)
    terms = load_vocab(config, preset="default")
    assert "Acme" in terms
    assert "Alice" in terms


def test_deduplication_preserves_order(tmp_path: Path) -> None:
    root = tmp_path
    (root / "config" / "vocab" / "projects").mkdir(parents=True)
    (root / "config" / "vocab" / "code.txt").write_text("alpha\nbeta\n")
    (root / "config" / "vocab" / "work.txt").write_text("beta\ngamma\n")
    (root / "config" / "vocab" / "personal.txt").write_text("")
    config = Config(root=root)
    terms = load_vocab(config, preset="code")
    assert terms.index("alpha") < terms.index("beta") < terms.index("gamma")
    assert terms.count("beta") == 1


def test_project_file_included_when_exists(tmp_path: Path) -> None:
    root = tmp_path
    proj_dir = root / "config" / "vocab" / "projects"
    proj_dir.mkdir(parents=True)
    (root / "config" / "vocab" / "code.txt").write_text("")
    (root / "config" / "vocab" / "work.txt").write_text("")
    (root / "config" / "vocab" / "personal.txt").write_text("")
    (proj_dir / "myapp.txt").write_text("MyApp\nWidgetFactory\n")
    config = Config(root=root)
    terms = load_vocab(config, preset="code", project="myapp")
    assert "MyApp" in terms
    assert "WidgetFactory" in terms


def test_project_file_missing_is_noop(tmp_path: Path) -> None:
    root = tmp_path
    (root / "config" / "vocab" / "projects").mkdir(parents=True)
    (root / "config" / "vocab" / "code.txt").write_text("")
    (root / "config" / "vocab" / "work.txt").write_text("Acme\n")
    (root / "config" / "vocab" / "personal.txt").write_text("")
    config = Config(root=root)
    terms = load_vocab(config, preset="default", project="nonexistent")
    assert terms == ["Acme"]


def test_skips_blank_lines_and_comments(tmp_path: Path) -> None:
    root = tmp_path
    (root / "config" / "vocab" / "projects").mkdir(parents=True)
    (root / "config" / "vocab" / "code.txt").write_text("")
    (root / "config" / "vocab" / "work.txt").write_text("# comment\n\nRealTerm\n")
    (root / "config" / "vocab" / "personal.txt").write_text("")
    config = Config(root=root)
    terms = load_vocab(config, preset="default")
    assert terms == ["RealTerm"]


def test_as_initial_prompt_truncates(tmp_path: Path) -> None:
    terms = ["alpha", "beta", "gamma", "delta"]
    result = as_initial_prompt(terms, max_chars=10)
    assert len(result) <= 10
    assert result == "alpha, bet"


def test_as_initial_prompt_full(tmp_path: Path) -> None:
    terms = ["a", "b"]
    assert as_initial_prompt(terms) == "a, b"


def test_real_config_code_vocab() -> None:
    config = Config.load(Path(__file__).resolve().parent.parent)
    terms = load_vocab(config, preset="code")
    assert "GitHub" in terms
    assert "TypeScript" in terms
