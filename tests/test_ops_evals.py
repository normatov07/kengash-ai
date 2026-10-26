"""Skill evals: scenarios, headless conductor runs, expectations (SP4 spec decisions 11-13)."""

import json
import re
import sys
from pathlib import Path
from typing import Any

import pytest
from conftest import FakeClis

from super_harness.model import EvalScenario, UserError
from super_harness.ops import evals, lifecycle

SCENARIO = """\
skill: to-plan
description: a direct plan from a short prompt
files:
  calc.py: "def sub(a, b):\\n    return a - b\\n"
settings: "plan.review_max: 0\\n"
setup:
  - args: [plan, new, --mode, direct, --title, Seed]
    stdin: "Seed prompt."
    save: seed
turns:
  - "/to-plan Add add(a, b) to calc.py"
expect:
  journal: [plan.created]
  absent: [plan.approved]
  plans: {min: 1, fields: {mode: direct}}
"""


def write(folder: Path, name: str, text: str) -> Path:
    path = folder / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_load_reads_a_scenario(tmp_path: Path) -> None:
    scenario = evals.load(write(tmp_path, "to-plan/direct.yaml", SCENARIO))
    assert isinstance(scenario, EvalScenario)
    assert (scenario.skill, scenario.setup[0].save, scenario.timeout_s) == ("to-plan", "seed", 900)
    assert scenario.expect.plans is not None and scenario.expect.plans.fields == {"mode": "direct"}


def test_load_names_the_file_and_the_bad_key(tmp_path: Path) -> None:
    path = write(tmp_path, "to-plan/typo.yaml", SCENARIO.replace("absent:", "absnet:"))
    with pytest.raises(UserError, match=r"typo\.yaml: .*absnet"):
        evals.load(path)


def test_scenarios_lists_one_skill_or_all(tmp_path: Path) -> None:
    write(tmp_path, "to-plan/b.yaml", SCENARIO)
    write(tmp_path, "to-plan/a.yaml", SCENARIO)
    write(tmp_path, "to-ticket/one.yaml", SCENARIO.replace("to-plan", "to-ticket"))
    assert [name for name, _ in evals.scenarios(tmp_path, "to-plan")] == ["to-plan/a", "to-plan/b"]
    assert len(evals.scenarios(tmp_path, None)) == 3
    with pytest.raises(UserError, match="no eval scenarios for to-loop"):
        evals.scenarios(tmp_path, "to-loop")


def test_fill_replaces_known_names_only() -> None:
    assert evals.fill("/to-ticket {plan} {other}", {"plan": "a1b2c3d4"}) == (
        "/to-ticket a1b2c3d4 {other}"
    )


PLAN_NEW = "harness plan new --mode direct --title Probe <<'EOF'\nAdd add(a, b).\nEOF"


def claude_reply(session: str = "s-1", result: str = "Planned it.") -> str:
    return json.dumps(
        {"type": "result", "is_error": False, "session_id": session, "result": result}
    )


def scenario(**fields: Any) -> EvalScenario:
    data: dict[str, Any] = {
        "skill": "to-plan",
        "turns": ["/to-plan Add add(a, b)"],
        "expect": {
            "journal": ["plan.created"],
            "plans": {"count": 1, "fields": {"mode": "direct"}},
        },
    }
    return EvalScenario.model_validate(data | fields)


@pytest.fixture
def source(tmp_path: Path) -> Path:
    folder = tmp_path / "skills"
    write(folder, "to-plan/SKILL.md", "---\nname: to-plan\ndescription: Use when.\n---\nPlan.\n")
    return folder


@pytest.fixture
def work(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.delenv("HARNESS_HOME", raising=False)
    return tmp_path / "work"


def run(work: Path, source: Path, case: EvalScenario, agent: str = "claude", **kw: Any) -> Any:
    return evals.run_scenario(
        "to-plan/probe", case, agent, work=work, model="haiku", source=source, **kw
    )


def test_a_scenario_passes_when_the_conductor_does_the_work(
    work: Path, source: Path, fake_clis: FakeClis
) -> None:
    fake_clis.queue("claude", stdout=claude_reply(), shell=PLAN_NEW)
    result = run(work, source, scenario(expect={"journal": ["plan.created"], "reply": ["Planned"]}))
    assert (result.passed, result.failure) == (True, "")
    (call,) = fake_clis.calls("claude")
    argv = call["argv"]
    assert argv[:2] == ["-p", "/to-plan Add add(a, b)"] and call["cwd"] == str(work / "repo")
    assert argv[argv.index("--model") + 1] == "haiku" and "dontAsk" in argv
    assert argv[-4:] == ["Read", "Grep", "Glob", "Bash(harness:*)"]
    assert call["env"]["HARNESS_AGENT"] == "claude" and "CLAUDECODE" not in call["env"]
    assert (work / "repo" / ".claude" / "skills" / "to-plan" / "SKILL.md").is_file()


def test_later_turns_resume_the_session(work: Path, source: Path, fake_clis: FakeClis) -> None:
    fake_clis.queue("claude", stdout=claude_reply(result="Which title?"))
    fake_clis.queue("claude", stdout=claude_reply(), shell=PLAN_NEW)
    case = scenario(turns=["/to-plan Add add(a, b)", "Call it Probe."])
    assert run(work, source, case).passed
    second = fake_clis.calls("claude")[1]["argv"]
    assert second[:2] == ["-p", "Call it Probe."] and second[second.index("--resume") + 1] == "s-1"


@pytest.mark.parametrize(
    ("expect", "failure"),
    [
        ({"journal": ["plan.saved"]}, "journal has no plan.saved"),
        ({"absent": ["plan.created"]}, "journal has plan.created"),
        ({"plans": {"count": 2}}, "plans: 1, expected 2"),
        ({"plans": {"min": 2}}, "plans: 1, expected at least 2"),
        (
            {"plans": {"fields": {"mode": "grill"}}},
            r"plan [0-9a-f]{8}: mode is direct, expected grill",
        ),
        ({"tickets": {"min": 1}}, "tickets: 0, expected at least 1"),
        ({"memory": ["likes tea"]}, 'MEMORY.md lacks "likes tea"'),
        ({"reply": ["Nope"]}, 'the reply lacks "Nope"'),
    ],
)
def test_each_failed_expectation_is_named(
    work: Path, source: Path, fake_clis: FakeClis, expect: dict[str, Any], failure: str
) -> None:
    fake_clis.queue("claude", stdout=claude_reply(), shell=PLAN_NEW)
    result = run(work, source, scenario(expect=expect))
    assert not result.passed and re.fullmatch(failure, result.failure), result.failure


def test_setup_saves_ids_for_later_steps(work: Path, source: Path, fake_clis: FakeClis) -> None:
    setup = [
        {
            "args": ["plan", "new", "--mode", "direct", "--title", "Seed"],
            "stdin": "Seed.",
            "save": "plan",
        },
        {"args": ["plan", "save", "{plan}"], "stdin": "## Goal\nShip it.\n"},
    ]
    fake_clis.queue("claude", stdout=claude_reply())
    case = scenario(
        setup=setup,
        turns=["/to-plan {plan}"],
        expect={"journal": ["plan.saved"], "plans": {"count": 1, "fields": {"id": "{plan}"}}},
    )
    result = run(work, source, case)
    assert result.passed, result.failure
    turn = fake_clis.calls("claude")[0]["argv"][1]
    assert re.fullmatch(r"/to-plan [0-9a-f]{8}", turn)


def test_baseline_runs_install_no_skills(work: Path, source: Path, fake_clis: FakeClis) -> None:
    fake_clis.queue("claude", stdout=claude_reply(), shell=PLAN_NEW)
    assert run(work, source, scenario(), baseline=True).passed
    assert not (work / "repo" / ".claude").exists()


def test_agy_conductors_run_sandboxed_without_prompts(
    work: Path, source: Path, fake_clis: FakeClis
) -> None:
    reply = json.dumps({"conversation_id": "c-1", "status": "SUCCESS", "response": "Planned."})
    fake_clis.queue("agy", stdout=reply, shell=PLAN_NEW)
    result = run(work, source, scenario(), agent="antigravity")
    assert result.passed, result.failure
    argv = fake_clis.calls("agy")[0]["argv"]
    assert argv[-2:] == ["--dangerously-skip-permissions", "--sandbox"]
    assert (work / "repo" / ".agents" / "skills" / "to-plan" / "SKILL.md").is_file()


def test_a_hanging_turn_times_out(work: Path, source: Path, fake_clis: FakeClis) -> None:
    fake_clis.queue("claude", stdout=claude_reply(), sleep=30)
    result = run(work, source, scenario(timeout_s=1))
    assert (result.passed, result.failure) == (False, "turn 1 timed out after 1 s")


def test_parse_turn_reads_each_agent() -> None:
    assert evals.parse_turn("claude", claude_reply()) == ("s-1", "Planned it.")
    agy = json.dumps({"conversation_id": "c-1", "response": "Done."})
    assert evals.parse_turn("antigravity", agy) == ("c-1", "Done.")
    codex = "\n".join(
        json.dumps(event)
        for event in (
            {"type": "thread.started", "thread_id": "t-1"},
            {"type": "item.completed", "item": {"type": "agent_message", "text": "Hi."}},
        )
    )
    assert evals.parse_turn("codex", codex) == ("t-1", "Hi.")
    assert evals.parse_turn("claude", "not json") == (None, "not json")


def test_settings_and_turns_get_the_agent_placeholders(
    work: Path, source: Path, fake_clis: FakeClis
) -> None:
    fake_clis.queue("claude", stdout=claude_reply(), shell=PLAN_NEW)
    case = scenario(settings="plan.reviewer: {cli}\n", turns=["/to-plan on {agent} {model}"])
    assert run(work, source, case).passed
    settings = (work / "home" / ".harness" / "defaults" / "SETTINGS.md").read_text()
    assert settings == "plan.reviewer: claude/haiku\n"
    assert fake_clis.calls("claude")[0]["argv"][1] == "/to-plan on claude haiku"
    assert evals.agent_values("codex", None) == {"agent": "codex", "model": "", "cli": "codex"}


def test_a_clean_expectation_names_changed_files(
    work: Path, source: Path, fake_clis: FakeClis
) -> None:
    fake_clis.queue("claude", stdout=claude_reply(), shell=f"{PLAN_NEW}\necho x > notes.md")
    result = run(work, source, scenario(expect={"clean": True}))
    assert (result.passed, result.failure) == (False, "the repo has changes: notes.md")


# A stand-in server started as `harness ui open` starts one: in a session of its own from
# the moment it runs, so the conductor's process group ending cannot take it down (a
# backgrounded process that calls setsid itself loses that race on slow starts, as on macOS),
# and recorded only once it is detached. Its streams go to /dev/null so the conductor's
# output closes when the conductor ends.
UI_STANDIN = (
    "import json, os, subprocess; "
    "quiet = subprocess.DEVNULL; "
    'home = os.environ["HARNESS_HOME"]; '
    'server = subprocess.Popen(["sleep", "60"], start_new_session=True, '
    "stdin=quiet, stdout=quiet, stderr=quiet); "
    'os.makedirs(home + "/runtime", exist_ok=True); '
    'record = {"pid": server.pid, "port": 1, "token": "t"}; '
    'json.dump(record, open(home + "/runtime/ui.json", "w")); '
    'open(home + "/../ui.pid", "w").write(str(server.pid))'
)
START_UI = f"'{sys.executable}' -c '{UI_STANDIN}'"


def test_a_ui_expectation_needs_a_running_server(
    work: Path, source: Path, fake_clis: FakeClis
) -> None:
    fake_clis.queue("claude", stdout=claude_reply())
    result = run(work, source, scenario(expect={"ui": True}))
    assert (result.passed, result.failure) == (False, "the UI server is not running")


def test_a_ui_the_conductor_starts_is_stopped_after_the_run(
    work: Path, source: Path, fake_clis: FakeClis
) -> None:
    fake_clis.queue("claude", stdout=claude_reply(), shell=START_UI)
    result = run(work, source, scenario(expect={"ui": True}))
    assert (result.passed, result.failure) == (True, "")
    record = work / "home" / ".harness" / "runtime" / "ui.json"
    pid = int((work / "home" / "ui.pid").read_text())
    assert not record.exists() and not lifecycle.pid_alive(pid)
    (call,) = fake_clis.calls("claude")
    assert call["env"]["BROWSER"] == "true"  # `harness ui open` opens no window in an eval
