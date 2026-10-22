DOCS_BASE ?= main
MAKEFLAGS += --silent

.PHONY: setup fmt lint type test docs check

setup:
	uv sync
	uv run pre-commit install

fmt:
	uv run ruff format .
	uv run ruff check --fix .

lint:
	uv run ruff format --check --quiet .
	uv run ruff check --quiet .
	out=$$(uv run lint-imports 2>&1) || { echo "$$out"; exit 1; }

type:
	uv run mypy --no-error-summary

test:
	uv run pytest

docs:
	uv run python scripts/check_md_caps.py
	uv run python scripts/check_docs_sync.py --base $(DOCS_BASE)

check: lint type test docs
