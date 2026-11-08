"""Findings are checked and only what matters blocks (SP17 spec §3.8, §3.9)."""

from pathlib import Path

from conftest import Engine, FakeClis, write_settings

from kengash_ai.model import Finding
from kengash_ai.ops import prompts, steps


def _finding(file: str, line: int = 1, severity: str = "high") -> Finding:
    return Finding(severity=severity, file=file, line=line, issue="bad", fix="fix")


def test_a_real_finding_stands(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("x\ny\n")
    assert prompts.checked_findings([_finding("a.py", 2)], tmp_path) == [_finding("a.py", 2)]


def test_a_missing_file_is_demoted(tmp_path: Path) -> None:
    [found] = prompts.checked_findings([_finding("ghost.py")], tmp_path)
    assert found.severity == "low" and found.issue.startswith("unverified")


def test_a_line_past_the_end_is_demoted(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("x\n")
    [found] = prompts.checked_findings([_finding("a.py", 99)], tmp_path)
    assert found.severity == "low" and "line 99" in found.issue


def test_a_path_outside_the_worktree_is_demoted(tmp_path: Path) -> None:
    [found] = prompts.checked_findings([_finding("../../etc/passwd")], tmp_path)
    assert found.severity == "low"


def test_an_empty_file_or_line_zero_is_left_alone(tmp_path: Path) -> None:
    findings = [_finding("", 0), _finding("Risks", 0)]
    assert prompts.checked_findings(findings, tmp_path) == findings


def _review(fake_clis: FakeClis, verdict: str, severity: str, file: str, line: int = 1) -> None:
    finding = {"severity": severity, "file": file, "line": line, "issue": "x", "fix": "y"}
    output = {"verdict": verdict, "summary": "s", "findings": [finding]}
    fake_clis.queue("claude", stdout=fake_clis.claude_output(output))


SIMPLE = "workflows:\n  simple: {steps: [review_code], on_fail: {}}\nrouting: {critical: simple}\n"


def _at_review(engine: Engine) -> None:
    from kengash_ai.store import documents

    doc = engine.ticket()
    doc.meta.step = "review_code"
    doc.meta.status = "in_process/under_review"
    documents.save_ticket(engine.paths.project(engine.slug), doc)


def test_only_low_findings_pass(engine: Engine, fake_clis: FakeClis) -> None:
    (engine.worktree / "a.py").write_text("x\n")
    _at_review(engine)
    _review(fake_clis, "fail", "low", "a.py")
    steps.run_job("7b55e0c1", steps=1)
    assert "· review_code · code-reviewer" in engine.ticket().sections["Log"]
    assert " · pass · " in engine.ticket().sections["Log"].splitlines()[-1]


def test_a_medium_finding_fails(engine: Engine, fake_clis: FakeClis) -> None:
    (engine.worktree / "a.py").write_text("x\n")
    _at_review(engine)
    _review(fake_clis, "fail", "medium", "a.py")
    steps.run_job("7b55e0c1", steps=1)
    assert " · fail · " in engine.ticket().sections["Log"].splitlines()[-1]


def test_a_hallucinated_finding_does_not_block(engine: Engine, fake_clis: FakeClis) -> None:
    _at_review(engine)
    _review(fake_clis, "fail", "high", "does/not/exist.py")
    steps.run_job("7b55e0c1", steps=1)
    assert " · pass · " in engine.ticket().sections["Log"].splitlines()[-1]


def test_block_on_can_widen(engine: Engine, fake_clis: FakeClis) -> None:
    write_settings(engine.paths, "review.block_on: [high, medium, low]\n")
    (engine.worktree / "a.py").write_text("x\n")
    _at_review(engine)
    _review(fake_clis, "fail", "low", "a.py")
    steps.run_job("7b55e0c1", steps=1)
    assert " · fail · " in engine.ticket().sections["Log"].splitlines()[-1]
