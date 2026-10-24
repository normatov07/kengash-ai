DOCS_BASE ?= main
MAKEFLAGS += --silent

.PHONY: setup fmt lint type test live evals docs check

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
	uv run harness skills lint

type:
	uv run mypy --no-error-summary

test:
	uv run pytest

# real provider CLIs on a scratch repo (SP3 spec §11); spends subscription quota
live:
	uv run pytest -m live -v

# every skill scenario on every installed agent (SP4 spec §2.17); spends subscription quota
evals:
	uv run harness skills eval --all

docs:
	uv run python scripts/check_md_caps.py
	uv run python scripts/check_docs_sync.py --base $(DOCS_BASE)

check: lint type test docs
