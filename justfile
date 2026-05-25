default:
    @just --list

install:
    pip install -e ".[dev]"

test *args:
    pytest -q {{args}}

lint:
    ruff check .

format:
    ruff format .

format-check:
    ruff format --check .

run:
    python -m dictate

web:
    python -m dictate.webui

clean:
    rm -rf build dist *.egg-info .pytest_cache .ruff_cache
    find . -type d -name __pycache__ -exec rm -rf {} +

package:
    @echo "Packaging .app bundle (not implemented yet — see ROADMAP.md v0.4)"

ci: lint format-check test
