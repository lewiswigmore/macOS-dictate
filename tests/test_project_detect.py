from __future__ import annotations

from pathlib import Path

import pytest

from dictate.config import Config, load_config
from dictate.project_detect import (
    available_projects,
    clear_cache,
    detect_project,
)


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    # Build a minimal repo skeleton with vocab/projects/<name>.txt files.
    (tmp_path / "config" / "vocab" / "projects").mkdir(parents=True)
    (tmp_path / "config" / "vocab" / "projects" / "dictate.txt").write_text("foo\n")
    (tmp_path / "config" / "vocab" / "projects" / "huntr.txt").write_text("bar\n")
    (tmp_path / "config" / "vocab" / "projects" / "openclaw.txt").write_text("baz\n")
    (tmp_path / "config" / "settings.yaml").write_text("logging:\n  level: INFO\n")
    monkeypatch.setenv("DICTATE_HOME", str(tmp_path))
    clear_cache()
    return load_config(tmp_path)


def test_available_projects_lists_stems(cfg: Config) -> None:
    projects = available_projects(cfg)
    assert set(projects.keys()) == {"dictate", "huntr", "openclaw"}
    assert all(p.is_file() for p in projects.values())


def test_available_projects_cached_by_mtime(cfg: Config) -> None:
    p1 = available_projects(cfg)
    p2 = available_projects(cfg)
    # Same dict instance returned when mtime unchanged.
    assert p1 is p2


def test_detect_project_simple_match(cfg: Config) -> None:
    projects = available_projects(cfg)
    assert detect_project("Dictate — README.md", projects) == "dictate"
    assert detect_project("zsh - huntr/api", projects) == "huntr"


def test_detect_project_case_insensitive(cfg: Config) -> None:
    projects = available_projects(cfg)
    assert detect_project("HUNTR pull request", projects) == "huntr"


def test_detect_project_word_boundary(cfg: Config) -> None:
    projects = available_projects(cfg)
    # "dictated" should NOT match "dictate" project.
    assert detect_project("I dictated some notes", projects) is None


def test_detect_project_prefers_longest_match(cfg: Config) -> None:
    # Add a longer name that also contains "huntr".
    (cfg.root / "config" / "vocab" / "projects" / "huntr-api.txt").write_text("x\n")
    clear_cache()
    projects = available_projects(cfg)
    assert detect_project("huntr-api dashboard", projects) == "huntr-api"


def test_detect_project_no_match(cfg: Config) -> None:
    projects = available_projects(cfg)
    assert detect_project("Slack — general", projects) is None
    assert detect_project(None, projects) is None
    assert detect_project("", projects) is None


def test_detect_project_empty_projects() -> None:
    assert detect_project("anything", {}) is None
