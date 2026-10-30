DOCS_BASE ?= main
MAKEFLAGS += --silent

.PHONY: setup fmt lint type test live evals docs check dist audit

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
	uv run kengash skills lint

type:
	uv run mypy --no-error-summary

test:
	uv run pytest

# real provider CLIs on a scratch repo (SP3 spec §11); spends subscription quota
live:
	uv run pytest -m live -v

# every skill scenario on every installed agent (SP4 spec §2.17); spends subscription quota
evals:
	uv run kengash skills eval --all

docs:
	uv run python scripts/check_md_caps.py
	uv run python scripts/check_docs_sync.py --base $(DOCS_BASE)

check: lint type test docs

# release artifacts, checked: the product and nothing local (SP7 spec decision 8)
dist:
	rm -rf dist
	uv build --quiet
	uv run python scripts/check_dist.py dist

# known vulnerabilities in the locked dependencies
audit:
	uv lock --check
	uv export --format requirements-txt --all-extras --no-emit-project --quiet > .audit-requirements.txt
	uvx pip-audit@2.10.1 -r .audit-requirements.txt --disable-pip --require-hashes; status=$$?; rm -f .audit-requirements.txt; exit $$status
