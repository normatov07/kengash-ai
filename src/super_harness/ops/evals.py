"""Skill evals (SP4 spec decisions 11 to 13): scenarios replayed headless against a
temporary store and scratch repo, on each agent, with their expectations checked."""

import re
from collections.abc import Mapping
from pathlib import Path

from pydantic import ValidationError

import super_harness
from super_harness.model import EvalScenario, UserError
from super_harness.ops import records
from super_harness.store.yamlio import load_yaml

EVALS_DIR = Path(super_harness.__file__).resolve().parents[2] / "evals"
PLACEHOLDER = re.compile(r"\{([a-z][a-z0-9_]*)\}")


def load(path: Path) -> EvalScenario:
    """One scenario file; a problem names the file."""
    try:
        return EvalScenario.model_validate(load_yaml(path.read_text(encoding="utf-8"), path.name))
    except ValidationError as exc:
        raise UserError(f"{path.name}: {records.describe(exc)}") from exc


def scenarios(root: Path, skill: str | None) -> list[tuple[str, Path]]:
    """`(<skill>/<scenario>, path)` for one skill's scenarios, or every skill's."""
    pattern = f"{skill}/*.yaml" if skill else "*/*.yaml"
    found = sorted(root.glob(pattern))
    if not found:
        raise UserError(f"no eval scenarios for {skill or 'any skill'} in {root}")
    return [(f"{path.parent.name}/{path.stem}", path) for path in found]


def fill(text: str, values: Mapping[str, str]) -> str:
    """`text` with each `{name}` that `values` knows replaced."""
    return PLACEHOLDER.sub(lambda match: values.get(match.group(1), match.group(0)), text)
