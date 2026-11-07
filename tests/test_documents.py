from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from kengash_ai.model import Doc, Folder, Plan, PlanMode, PlanStatus, Ticket
from kengash_ai.store import documents
from kengash_ai.store.paths import ProjectPaths

MakeTicket = Callable[..., Doc[Ticket]]
NOW = datetime(2026, 10, 22, 9, 41, tzinfo=UTC)


def test_ticket_round_trip(tmp_path: Path, make_ticket: MakeTicket) -> None:
    project = ProjectPaths(tmp_path)
    doc = make_ticket()
    path = documents.save_ticket(project, doc)
    assert path == project.folder(Folder.in_queue) / "7b55e0c1.md"
    loaded = documents.load_ticket(path)
    assert loaded.meta == doc.meta
    assert loaded.sections["Scope"] == "Rotate keys."


def test_saving_a_new_status_moves_the_file(tmp_path: Path, make_ticket: MakeTicket) -> None:
    project = ProjectPaths(tmp_path)
    doc = make_ticket()
    documents.save_ticket(project, doc)
    doc.meta.status = "in_process/under_planning"
    path = documents.save_ticket(project, doc)
    assert path.parent == project.folder(Folder.in_process)
    assert documents.find_ticket(project, "7b55e0c1") == path
    assert not (project.folder(Folder.in_queue) / "7b55e0c1.md").exists()


def test_plan_round_trip(tmp_path: Path) -> None:
    project = ProjectPaths(tmp_path)
    plan = Plan(
        id="a1b2c3d4",
        uuid=uuid4(),
        project="payments-api",
        title="Rotatable keys",
        mode=PlanMode.direct,
        status=PlanStatus.draft,
        created=NOW,
        updated=NOW,
    )
    prompt = "Make keys rotatable.\n## Goal\nas the user typed it"
    path = documents.save_plan(project, Doc(plan, {"Prompt": prompt}))
    loaded = documents.load_plan(path)
    assert loaded.meta == plan
    assert loaded.sections["Prompt"] == prompt


def test_check_document_reports_problems(tmp_path: Path, make_ticket: MakeTicket) -> None:
    project = ProjectPaths(tmp_path)
    path = documents.save_ticket(project, make_ticket())
    assert documents.check_document(path, "ticket") is None
    moved = project.folder(Folder.done) / path.name
    moved.parent.mkdir(parents=True)
    path.rename(moved)
    assert documents.check_document(moved, "ticket") == "in done/ but status says in_queue/ready"
    moved.write_text("---\nid: nope\n---\n", encoding="utf-8")
    problem = documents.check_document(moved, "ticket")
    assert problem is not None
    assert problem.startswith("invalid id: ")


def test_check_output_is_saved_between_findings_and_log(
    tmp_path: Path, make_ticket: MakeTicket
) -> None:
    project = ProjectPaths(tmp_path)
    doc = make_ticket()
    doc.sections["Findings"] = "- high · -:0 · `x` exit 1: error · fix"
    doc.sections["Check output"] = "`x` exit 1: error\n```text\nerror\n```"
    path = documents.save_ticket(project, doc)
    text = path.read_text(encoding="utf-8")
    assert text.index("## Findings") < text.index("## Check output") < text.index("## Log")
    assert documents.load_ticket(path).sections["Check output"] == doc.sections["Check output"]
