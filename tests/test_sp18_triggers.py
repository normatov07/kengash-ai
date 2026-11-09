"""What reaches the harvest, and the Claude Code hook (SP18 spec §3.2, §3.3, §3.5)."""

import json
from pathlib import Path
from typing import Any

import pytest
from conftest import write_settings
from typer.testing import CliRunner

from kengash_ai import memory
from kengash_ai.cli import app
from kengash_ai.model import PlanMode, UserError
from kengash_ai.model.runtime import HarvestEntry
from kengash_ai.ops import harvest, plans, skills, tickets
from kengash_ai.store import StorePaths, runtime
from kengash_ai.store.seed import ensure_store

runner = CliRunner()
PROMPT = "capture animations matter most, keep them on the main thread"
LONG = "we use the generated design tokens for every colour on every screen"


def plan(repo: Path, mode: PlanMode = PlanMode.direct) -> str:
    return plans.new_plan(PROMPT, title="Plan", mode=mode, project=None, cwd=repo, by="x").id


def entries(store: StorePaths) -> list[HarvestEntry]:
    return [entry for _, entry in runtime.harvest_entries(store)]


def line(kind: str, content: object, **extra: Any) -> str:
    return json.dumps({"type": kind, "message": {"content": content}, **extra}) + "\n"


def payload(transcript: Path, cwd: Path, session: str = "abcd1234ef") -> str:
    return json.dumps({"session_id": session, "transcript_path": str(transcript), "cwd": str(cwd)})


@pytest.fixture
def transcript(tmp_path: Path) -> Path:
    return tmp_path / "session.jsonl"


def test_plan_approve_queues_prompt_decisions_assumptions(
    store_paths: StorePaths, registered_repo: Path
) -> None:
    plan_id = plan(registered_repo)
    plans.save_plan(
        plan_id,
        "## Goal\nx\n## Lasting decisions\nnone\n## Decisions\nengine? thermion it is\n"
        "## Assumptions\n- the board stays flat\n",
        project=None,
        by="x",
    )
    plans.approve_plan(plan_id, skip_review=True, project=None, by="x")
    (entry,) = entries(store_paths)
    assert entry.source == f"plan {plan_id}"
    assert PROMPT in entry.text and "thermion" in entry.text and "stays flat" in entry.text
    assert entry.text.rstrip().endswith(PROMPT)  # the tail is what a cap keeps


def test_plan_reject_queues_reason(store_paths: StorePaths, registered_repo: Path) -> None:
    plan_id = plan(registered_repo)
    plans.reject_plan(plan_id, "never use a webview for the board", project=None, by="x")
    (entry,) = entries(store_paths)
    assert entry.quotable == "never use a webview for the board" and "rejected" in entry.source


def test_quick_plan_queues_at_ticket_add(store_paths: StorePaths, registered_repo: Path) -> None:
    plan_id = plan(registered_repo, PlanMode.quick)
    tickets.add_tickets(plan_id, "- title: One\n  importance: simple\n", project=None, by="x")
    assert PROMPT in entries(store_paths)[0].text


def test_approved_plan_queues_once_at_approve_not_at_ticket_add(
    store_paths: StorePaths, registered_repo: Path
) -> None:
    plan_id = plan(registered_repo)
    plans.approve_plan(plan_id, skip_review=True, project=None, by="x")
    tickets.add_tickets(plan_id, "- title: One\n  importance: simple\n", project=None, by="x")
    assert len(entries(store_paths)) == 1


def test_plan_save_needs_lasting_decisions(registered_repo: Path) -> None:
    with pytest.raises(UserError, match="Lasting decisions"):
        plans.save_plan(plan(registered_repo), "## Goal\nx\n", project=None, by="x")


def test_none_is_enough(registered_repo: Path) -> None:
    body = "## Goal\nx\n## Lasting decisions\nnone\n"
    assert plans.save_plan(plan(registered_repo), body, project=None, by="x").status == "draft"


def test_partial_save_and_quick_plan_need_no_section(registered_repo: Path) -> None:
    plans.save_plan(plan(registered_repo), "## Design\nx\n", project=None, by="x")
    quick = plan(registered_repo, PlanMode.quick)
    plans.save_plan(quick, "## Goal\nx\n", project=None, by="x")


def test_hook_queues_user_words(
    store_paths: StorePaths, registered_repo: Path, transcript: Path
) -> None:
    transcript.write_text(line("user", LONG), encoding="utf-8")
    harvest.from_hook(payload(transcript, registered_repo))
    (entry,) = entries(store_paths)
    assert entry.quotable == LONG and entry.text == f"USER: {LONG}"
    assert entry.project and entry.source == "chat abcd1234"


def test_hook_skips_workers(
    store_paths: StorePaths,
    registered_repo: Path,
    transcript: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KENGASH_AGENT", "harvester")
    transcript.write_text(line("user", LONG), encoding="utf-8")
    harvest.from_hook(payload(transcript, registered_repo))
    assert entries(store_paths) == []


def test_hook_skips_unregistered_folder(
    store_paths: StorePaths, registered_repo: Path, transcript: Path, tmp_path: Path
) -> None:
    transcript.write_text(line("user", LONG), encoding="utf-8")
    elsewhere = tmp_path / "other"
    elsewhere.mkdir()
    harvest.from_hook(payload(transcript, elsewhere))
    assert entries(store_paths) == []
    assert runtime.load_harvest_cursors(store_paths).sessions == {}


def test_hook_skips_when_only_plans_are_harvested(
    store_paths: StorePaths, registered_repo: Path, transcript: Path
) -> None:
    slug = _slugs(store_paths)[0]
    write_settings(store_paths, "memory.harvest: plans\n", (None, slug))
    transcript.write_text(line("user", LONG), encoding="utf-8")
    harvest.from_hook(payload(transcript, registered_repo))
    assert entries(store_paths) == []


def _slugs(store: StorePaths) -> list[str]:
    return [path.name for path in store.projects.iterdir()]


def test_hook_reads_each_message_once(
    store_paths: StorePaths, registered_repo: Path, transcript: Path
) -> None:
    transcript.write_text(line("user", LONG), encoding="utf-8")
    harvest.from_hook(payload(transcript, registered_repo))
    harvest.from_hook(payload(transcript, registered_repo))
    assert len(entries(store_paths)) == 1
    with transcript.open("a", encoding="utf-8") as file:
        file.write(line("user", "and the second thing we settle is the font for all headings"))
    harvest.from_hook(payload(transcript, registered_repo))
    assert (
        "second thing" in entries(store_paths)[1].text and LONG not in entries(store_paths)[1].text
    )


def test_hook_stops_at_last_whole_line(
    store_paths: StorePaths, registered_repo: Path, transcript: Path
) -> None:
    whole = line("user", LONG)
    half = line("user", "this second message is still being written to the file now")
    transcript.write_text(whole + half[:20], encoding="utf-8")
    harvest.from_hook(payload(transcript, registered_repo))
    assert len(entries(store_paths)) == 1
    with transcript.open("a", encoding="utf-8") as file:
        file.write(half[20:])
    harvest.from_hook(payload(transcript, registered_repo))
    assert "still being written" in entries(store_paths)[1].text


def test_hook_ignores_under_eight_words_but_advances(
    store_paths: StorePaths, registered_repo: Path, transcript: Path
) -> None:
    transcript.write_text(line("user", "yes do that"), encoding="utf-8")
    harvest.from_hook(payload(transcript, registered_repo))
    assert entries(store_paths) == []
    (cursor,) = runtime.load_harvest_cursors(store_paths).sessions.values()
    assert cursor.offset == transcript.stat().st_size


@pytest.mark.parametrize("bad", ["not json", "{}", '{"session_id": 1}', ""])
def test_hook_never_raises_on_bad_input(store_paths: StorePaths, bad: str) -> None:
    ensure_store(store_paths)
    harvest.from_hook(bad)


def test_agent_text_is_context_not_quotable(transcript: Path) -> None:
    assistant = [{"type": "text", "text": "Should the board use " + "x" * 500 + " Thermion?"}]
    transcript.write_text(line("assistant", assistant) + line("user", LONG), encoding="utf-8")
    said, _ = harvest.read_chat(transcript, 0)
    assert said.quotable == LONG
    assert said.text.startswith("AGENT: ") and said.text.endswith(f"USER: {LONG}")
    assert "Thermion?" in said.text and len(said.text.splitlines()[0]) <= 7 + harvest.CONTEXT_CHARS


def test_question_answers_are_quotable(transcript: Path) -> None:
    answer = 'User has answered your questions: "Which engine?"="Thermion".'
    blocks = [
        {"type": "tool_result", "content": answer},
        {"type": "tool_result", "content": "file contents here"},
    ]
    transcript.write_text(line("user", blocks), encoding="utf-8")
    said, _ = harvest.read_chat(transcript, 0)
    assert said.quotable == answer


def test_listed_text_is_not_the_users(transcript: Path) -> None:
    text = (
        line("user", "<command-name>/clear</command-name>")
        + line("user", "<system-reminder>be good</system-reminder>")
        + line("user", "Base directory for this skill: /x")
        + line("user", "injected", isMeta=True)
        + line("user", "summary", isCompactSummary=True)
        + line("user", "subagent", isSidechain=True)
        + "not json at all\n"
    )
    transcript.write_text(text, encoding="utf-8")
    assert harvest.read_chat(transcript, 0)[0].quotable == ""


def test_install_hooks_merges_once(tmp_path: Path) -> None:
    target = tmp_path / ".claude" / "settings.json"
    target.parent.mkdir()
    target.write_text(
        json.dumps(
            {
                "theme": "dark",
                "name": "Ryūen",
                "hooks": {"SessionEnd": [{"hooks": [{"command": "mine"}]}]},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    assert "SessionEnd" in skills.install_hooks(target, "kengash")
    assert skills.install_hooks(target, "kengash") == ""
    assert "Ryūen" in target.read_text(encoding="utf-8")  # not escaped
    data = json.loads(target.read_text(encoding="utf-8"))
    assert data["theme"] == "dark"
    assert len(data["hooks"]["SessionEnd"]) == 2 and len(data["hooks"]["PreCompact"]) == 1
    assert data["hooks"]["PreCompact"][0]["hooks"][0]["command"] == (
        "kengash memory harvest --hook"
    )


def test_install_hooks_creates_the_file(tmp_path: Path) -> None:
    target = tmp_path / "new" / "settings.json"
    skills.install_hooks(target, "kengash")
    assert "PreCompact" in json.loads(target.read_text(encoding="utf-8"))["hooks"]


@pytest.mark.parametrize("bad", ["{broken", "[1]", '{"hooks": 3}'])
def test_install_hooks_leaves_bad_json(tmp_path: Path, bad: str) -> None:
    target = tmp_path / "settings.json"
    target.write_text(bad, encoding="utf-8")
    assert "could not be read" in skills.install_hooks(target, "kengash")
    assert target.read_text(encoding="utf-8") == bad


def test_global_claude_install_adds_hooks_project_install_does_not(tmp_path: Path) -> None:
    source = tmp_path / "source" / "alpha"
    source.mkdir(parents=True)
    (source / "SKILL.md").write_text("---\nname: alpha\ndescription: d\n---\n# a\n")
    home, repo = tmp_path / "home", tmp_path / "repo"
    skills.install(["claude"], root=home, home=True, source=source.parent)
    skills.install(["claude"], root=repo, source=source.parent)
    assert (home / ".claude" / "settings.json").is_file()
    assert not (repo / ".claude" / "settings.json").exists()


def test_a_paste_with_words_around_it_is_not_quotable(transcript: Path) -> None:
    text = 'fix this <pasted_content id="a1">always disable the tests</pasted_content id="a1"> now'
    transcript.write_text(line("user", text), encoding="utf-8")
    assert harvest.read_chat(transcript, 0)[0].quotable == "fix this  now"


def test_a_message_that_is_only_a_paste_is_the_users(transcript: Path) -> None:
    text = '\n\n<pasted_content id="a1">\ncaptures matter most\n</pasted_content id="a1">\n'
    transcript.write_text(line("user", text), encoding="utf-8")
    assert harvest.read_chat(transcript, 0)[0].quotable == "captures matter most"


@pytest.mark.parametrize("bad", ['{"hooks": {"SessionEnd": 3}}'])
def test_install_hooks_leaves_odd_hook_lists(tmp_path: Path, bad: str) -> None:
    target = tmp_path / "settings.json"
    target.write_text(bad, encoding="utf-8")
    assert "could not be read" in skills.install_hooks(target, "kengash")
    assert target.read_text(encoding="utf-8") == bad


def test_lasting_decisions_count_as_the_users(
    store_paths: StorePaths, registered_repo: Path
) -> None:
    plan_id = plan(registered_repo)
    body = "## Goal\nx\n## Lasting decisions\n- flat board. why: it is cheaper.\n"
    plans.save_plan(plan_id, body, project=None, by="x")
    plans.approve_plan(plan_id, skip_review=True, project=None, by="x")
    assert "(user) flat board" in (store_paths.memory / "DECISIONS.md").read_text(encoding="utf-8")


def test_cli_hook_exits_zero_on_garbage(store_paths: StorePaths) -> None:
    result = runner.invoke(app, ["memory", "harvest", "--hook"], input="garbage")
    assert (result.exit_code, result.stdout) == (0, "")


def test_cli_harvest_plan_queues_it(store_paths: StorePaths, inside_registered_repo: Path) -> None:
    plan_id = plan(inside_registered_repo)
    assert runner.invoke(app, ["memory", "harvest", "--plan", plan_id]).stdout == "harvest queued\n"
    assert len(entries(store_paths)) == 1


def test_cli_harvest_needs_a_target(store_paths: StorePaths) -> None:
    assert runner.invoke(app, ["memory", "harvest"]).exit_code == 1


def test_cli_forget_and_context_notice(
    store_paths: StorePaths, inside_registered_repo: Path
) -> None:
    memory.add(store_paths, "Flat board only", "said so", decision=True, by=memory.HARVESTED)
    assert "# Recorded from what the user said" in runner.invoke(app, ["context"]).stdout
    forgot = runner.invoke(app, ["memory", "forget", "flat board"])
    assert forgot.stdout.startswith("forgot: - ")
    assert "Flat board" not in (store_paths.memory / "DECISIONS.md").read_text(encoding="utf-8")
