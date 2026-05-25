from __future__ import annotations

from dictate.config import load_config
from dictate.webui.server import run


def main() -> None:
    run(load_config())


__all__ = ["main", "run"]
