"""Step contract: requests, results, usage and output schemas (SP3 spec §8)."""

from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from kengash_ai.model import (
    OUTPUT_SCHEMAS,
    CompactOutput,
    Finding,
    ProviderStatus,
    ReviewOutput,
    StepRequest,
    StepResult,
    Usage,
    WorkOutput,
    parse_output,
)


def _objects(node: object) -> list[dict[str, Any]]:
    """Every JSON-schema object node in `node`."""
    found: list[dict[str, Any]] = []
    if isinstance(node, dict):
        if node.get("type") == "object":
            found.append(node)
        for child in node.values():
            found += _objects(child)
    elif isinstance(node, list):
        for child in node:
            found += _objects(child)
    return found


def test_output_schemas_are_strict_and_match_the_models() -> None:
    models: dict[str, type[BaseModel]] = {
        "work": WorkOutput,
        "review": ReviewOutput,
        "compact": CompactOutput,
    }
    for kind, schema in OUTPUT_SCHEMAS.items():
        assert set(schema["properties"]) == set(models[kind].model_fields)
        for node in _objects(schema):
            assert node["additionalProperties"] is False
            assert sorted(node["required"]) == sorted(node["properties"])
    finding = OUTPUT_SCHEMAS["review"]["properties"]["findings"]["items"]
    assert set(finding["properties"]) == set(Finding.model_fields)


def test_parse_output_validates_each_kind() -> None:
    assert parse_output("work", {"summary": "s", "handoff": "h"}) == WorkOutput(
        summary="s", handoff="h"
    )
    review = {
        "verdict": "fail",
        "summary": "s",
        "findings": [{"severity": "low", "file": "a.py", "line": 1, "issue": "i", "fix": "f"}],
    }
    assert isinstance(parse_output("review", review), ReviewOutput)
    with pytest.raises(ValueError, match="a failing verdict needs findings"):
        parse_output("review", {"verdict": "fail", "summary": "s", "findings": []})
    with pytest.raises(ValueError):
        parse_output("compact", {"text": "x", "extra": 1})


def test_usage_counts_input_and_output_and_subtracts_totals() -> None:
    total = Usage(input=100, output=40, cache_read=500, cost_usd=0.1)
    assert total.tokens == 140
    assert total.minus(Usage(input=60, output=50)) == Usage(input=40, output=0, cache_read=500)
    assert total.minus(None) == total.model_copy(update={"cost_usd": None})


def test_resuming_needs_a_session_id(tmp_path: Path) -> None:
    base = {
        "role": "implementer",
        "cwd": tmp_path,
        "prompt": "p",
        "output": "work",
        "profile": "edit_worktree",
        "timeout_s": 60,
        "log": tmp_path / "1.out",
    }
    assert StepRequest.model_validate(base).resume is False
    with pytest.raises(ValidationError, match="resume needs a session_id"):
        StepRequest.model_validate(base | {"resume": True})


def test_results_are_ok_without_an_error() -> None:
    assert StepResult().ok is True
    assert StepResult(error="auth").ok is False
    assert StepResult(error="auth").model_dump()["ok"] is False
    assert ProviderStatus(name="codex", installed=True).usable is False
