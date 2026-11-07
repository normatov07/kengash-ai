"""What a worker did, read from its stream logs (SP12 spec §4.4)."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from conftest import FAKES, Engine, FakeClis

from kengash_ai import journal
from kengash_ai.model import Event
from kengash_ai.ops import activity
from kengash_ai.store import documents

T0 = datetime(2026, 11, 6, 6, 5, tzinfo=UTC)
WORK = Path("/work")


def _fixture(name: str) -> str:
    return (FAKES / "fixtures" / name).read_text(encoding="utf-8")


def _texts(found: list[activity.Activity]) -> list[tuple[str, str]]:
    return [(item.kind, item.text) for item in found]


def test_agy_actions() -> None:
    found = activity.parse(_fixture("agy/stream-ok.jsonl"), root=WORK)
    assert _texts(found) == [
        ("read", "read pubspec.yaml"),
        ("edit", "edit lib/main.dart"),
        ("reply", "reply: Rebrand core package and UI to Chess Samurai"),
    ]


def test_agy_late_error_shows_reply_and_warning() -> None:
    found = activity.parse(_fixture("agy/stream-error-valid.jsonl"), root=WORK)
    assert _texts(found)[-2][1] == "reply: Rebrand core package and UI to Chess Samurai"
    kind, text = _texts(found)[-1]
    assert kind == "error" and "connection reset by peer" in text


def test_claude_actions() -> None:
    found = activity.parse(_fixture("claude/stream-ok.jsonl"), root=WORK)
    assert _texts(found) == [
        ("read", "read calc.py"),
        ("edit", "edit calc.py"),
        ("run", "run python3 -c 'import calc'"),
        ("reply", "reply: Add add(a, b) to calc.py"),
    ]


def test_codex_actions() -> None:
    found = activity.parse(_fixture("codex/stream-actions.jsonl"), root=WORK)
    assert _texts(found) == [
        ("run", "run bash -lc 'cat retry.py'"),
        ("edit", "edit retry.py"),
        ("reply", "reply: Added retry with backoff."),
    ]


def test_stamps_time_each_line() -> None:
    text = _fixture("codex/stream-actions.jsonl")
    stamps = [T0 + timedelta(seconds=n) for n in range(len(text.splitlines()))]
    found = activity.parse(text, stamps, root=WORK)
    assert [item.ts for item in found] == [stamps[2], stamps[3], stamps[4]]


def _log(engine: Engine, number: int, fixture: str, start: datetime) -> None:
    log = engine.paths.logs / f"{engine.ticket_id}-{number}.out"
    log.parent.mkdir(parents=True, exist_ok=True)
    text = _fixture(fixture)
    log.write_text(text, encoding="utf-8")
    stamps = [(start + timedelta(seconds=n)).isoformat() for n in range(len(text.splitlines()))]
    log.with_suffix(".ts").write_text("\n".join(stamps) + "\n", encoding="utf-8")


def _event(engine: Engine, ts: datetime, kind: str, **fields: object) -> None:
    data = {"ts": ts, "type": kind, "project": engine.slug, "ticket": engine.ticket_id, **fields}
    journal.append(engine.paths, Event.model_validate(data))


def test_activity_reads_each_provider_in_order(engine: Engine) -> None:
    _event(engine, T0, "step.start", step="plan", role="planner", provider="claude")
    _log(engine, 1, "claude/stream-ok.jsonl", T0 + timedelta(seconds=1))
    _event(
        engine, T0 + timedelta(minutes=1), "step.start", step="implement", provider="antigravity"
    )
    _log(engine, 2, "agy/stream-ok.jsonl", T0 + timedelta(minutes=1, seconds=1))
    found = activity.ticket(engine.paths, engine.slug, engine.ticket_id, root=WORK)
    texts = [text for _, text in _texts(found)]
    assert texts[0] == "plan → claude" and texts[5] == "implement → antigravity"
    assert texts[1] == "read calc.py" and texts[6] == "read pubspec.yaml"
    assert [item.ts for item in found] == sorted(item.ts for item in found if item.ts)


def test_follow_ends_with_the_ticket(engine: Engine) -> None:
    _event(engine, T0, "step.start", step="plan", provider="claude")
    _log(engine, 1, "claude/stream-ok.jsonl", T0 + timedelta(seconds=1))
    doc = engine.ticket()
    doc.meta.status = "done/merged"
    doc.meta.step = None
    documents.save_ticket(engine.paths.project(engine.slug), doc)
    beats = activity.follow(engine.paths, engine.slug, engine.ticket_id, poll_s=0.01, root=WORK)
    found = [item for item in beats if item is not None]
    assert found[0].text == "plan → claude" and found[-1].kind == "status"
    assert found[-1].text == "done/merged"
    assert json.dumps([item.text for item in found])  # plain strings all the way


def test_follow_heartbeats_while_quiet(engine: Engine) -> None:
    doc = engine.ticket()
    doc.meta.status, doc.meta.step = "in_process/under_implementation", "implement"
    documents.save_ticket(engine.paths.project(engine.slug), doc)
    _event(engine, T0, "step.start", step="implement", provider="antigravity")
    beats = activity.follow(
        engine.paths, engine.slug, engine.ticket_id, heartbeat=True, sleep=lambda s: None
    )
    first = next(beats)
    assert first is not None and first.text == "implement → antigravity"
    assert next(beats) is None  # nothing new: a heartbeat, so a stream can check its client


def test_a_line_separator_inside_json_keeps_the_event() -> None:
    from kengash_ai.adapters import stream

    event = {"type": "result", "result": "a\u2028b", "is_error": False}
    text = json.dumps({"type": "system"}) + "\n" + json.dumps(event, ensure_ascii=False) + "\n"
    found = stream.result(text, key="type", value="result")
    assert found is not None and found["result"] == "a\u2028b"


def test_ticket_reads_the_journal_from_the_tickets_day(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[object] = []
    real = journal.read

    def spy(paths: object, since: object = None) -> object:
        seen.append(since)
        return real(paths, since)  # type: ignore[arg-type]

    monkeypatch.setattr(journal, "read", spy)
    activity.ticket(engine.paths, engine.slug, engine.ticket_id)
    assert seen == [engine.ticket().meta.created.date()]


def test_a_cut_log_says_earlier_actions_are_omitted(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(activity, "TAIL_BYTES", 800)  # keeps only the last line, the reply
    _log(engine, 1, "agy/stream-ok.jsonl", T0)
    found = activity.ticket(engine.paths, engine.slug, engine.ticket_id)
    log = engine.paths.logs / f"{engine.ticket_id}-1.out"
    notes = [item for item in found if "omitted" in item.text]
    assert _texts(notes) == [("status", f"earlier actions omitted; full log: {log}")]
    after = found[found.index(notes[0]) + 1 :]
    assert after and all(item.ts is not None and item.ts >= T0 for item in after)


def test_a_whole_log_has_no_omitted_note(engine: Engine) -> None:
    _log(engine, 1, "agy/stream-ok.jsonl", T0)
    found = activity.ticket(engine.paths, engine.slug, engine.ticket_id)
    assert not [item for item in found if "omitted" in item.text]


def test_a_step_start_names_the_model(engine: Engine) -> None:
    _event(engine, T0, "step.start", step="implement", provider="antigravity", model="flash")
    found = activity.ticket(engine.paths, engine.slug, engine.ticket_id)
    assert found[0].text == "implement → antigravity/flash"


def test_the_journal_names_each_steps_model(engine: Engine, fake_clis: FakeClis) -> None:
    from kengash_ai.ops import steps

    fake_clis.queue("claude", fixture="claude/work_resume.json")
    steps.run_job(engine.ticket_id)
    found = activity.ticket(engine.paths, engine.slug, engine.ticket_id)
    assert found[0].text == "plan → claude/opus"


def test_watch_follows_through_a_gate_until_the_ticket_is_done(engine: Engine) -> None:
    project = engine.paths.project(engine.slug)
    doc = engine.ticket()
    doc.meta.status, doc.meta.step = "in_process/needs_approval", "implement"
    documents.save_ticket(project, doc)
    _event(engine, T0, "step.start", step="implement", provider="antigravity")
    naps: list[float] = []

    def nap(seconds: float) -> None:  # the user approves, the ticket runs, then merges
        naps.append(seconds)
        later = engine.ticket()
        later.meta.status = ["in_process/under_implementation", "done/merged"][
            min(len(naps), 2) - 1
        ]
        documents.save_ticket(project, later)

    found = activity.follow(
        engine.paths, engine.slug, engine.ticket_id, until_done=True, sleep=nap, root=WORK
    )
    texts = [item.text for item in found if item is not None]
    assert texts == ["implement → antigravity", "in_process/needs_approval", "done/merged"]
    assert naps == [activity.IDLE_POLL_S, 1.0]  # slower while nothing runs
