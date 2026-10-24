# SP4 M2: Eval Runner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `harness skills eval` replays `evals/<skill>/*.yaml` scenarios headless on claude, agy (and codex), in a temporary store and scratch repo, and checks store state, journal events and replies.

**Architecture:** `model.evals` holds the scenario schema. `ops.evals` builds the sandbox (store, repo, settings, setup commands, installed skills), runs each conductor turn through `adapters.process.run_process` with the agent's conductor flags, resumes the session between turns, stops leftover workers, and checks the expectations. `cli` formats one line per run.

**Tech Stack:** Python 3.12, pydantic 2, ruamel-yaml, Typer, subprocess, pytest with the fake CLIs.

**Spec:** `docs/superpowers/specs/2026-10-23-sp4-skills-design.md` (decisions 11–13, 16–17, §4, §5).

## Global Constraints

- Conductor flags (spec §5): claude `-p <turn> --output-format json [--model M] --setting-sources project,local --strict-mcp-config --permission-mode dontAsk --allowedTools Read Grep Glob "Bash(harness:*)"` (`--resume <id>` after the first turn); agy `-p <turn> --output-format json [--model M] --dangerously-skip-permissions --sandbox` (`--conversation <id>`); codex `exec --json --ignore-user-config --dangerously-bypass-approvals-and-sandbox [-m M] <turn>` / `exec resume --json … <id> <turn>` (documentation only).
- The conductor's environment is `adapters.env.worker_env(os.environ, provider, <agent name>, allow_api_key=False)` plus `HARNESS_HOME`, a scratch git identity, and this interpreter's `bin/` first on `PATH`.
- Cheapest models: claude `haiku`, agy `gemini-3.8-flash-low`, codex default.
- No test outside `tests/live/` runs a real CLI. Module docs change with modules. Commits end with the Co-Authored-By line.

## Review Focus

1. A conductor turn that hangs: killed at the scenario's `timeout_s`, reported as `fail: turn 1 timed out` (Task 2).
2. Workers a conductor started (`harness run`) are stopped when the scenario ends (Task 2).
3. A scenario file with a typo key fails to load with the file name and the key (Task 1).
4. `{name}` placeholders from `save:` work in later setup args, stdin, turns and expected fields (Task 1, 2).
5. An agent listed with `--agent` that is not installed or signed out exits 4 before any scenario runs (Task 3).

---

### Task 1: Scenario schema and loading

**Files:** Create `src/super_harness/model/evals.py`; Modify `src/super_harness/model/__init__.py`; Create `src/super_harness/ops/evals.py` (loading only); Test `tests/test_ops_evals.py`.

**Interfaces:**
- `model.SetupStep(args: list[str], stdin: str = "", save: str | None = None)`.
- `model.RecordsExpect(count: int | None = None, min: int | None = None, fields: dict[str, str] = {})`: `fields` keys may be dotted (`review.round`); values compare as strings.
- `model.Expect(journal: list[str] = [], absent: list[str] = [], plans: RecordsExpect | None = None, tickets: RecordsExpect | None = None, memory: list[str] = [], decisions: list[str] = [], reply: list[str] = [])`.
- `model.EvalScenario(skill: str, description: str = "", notes: str = "", files: dict[str, str] = {}, settings: str = "", setup: list[SetupStep] = [], turns: list[str] (min 1), expect: Expect, timeout_s: int = 900)`; all models forbid extra keys.
- `ops.evals.EVALS_DIR`: the checkout's `evals/`; `ops.evals.load(path: Path) -> EvalScenario` (`UserError` naming the file and the problem); `ops.evals.scenarios(root: Path, skill: str | None) -> list[tuple[str, Path]]` (`<skill>/<stem>` names, sorted; `UserError` when the skill has none); `ops.evals.fill(text: str, values: Mapping[str, str]) -> str` (`{name}` → value; unknown names stay).

- [ ] Tests: `test_load_reads_a_scenario`, `test_load_names_the_file_and_the_bad_key`, `test_scenarios_lists_one_skill_or_all`, `test_fill_replaces_known_names_only`; run FAIL; implement; run PASS; commit `feat: eval scenario schema`.

### Task 2: Running a scenario

**Files:** Modify `src/super_harness/ops/evals.py`; Test `tests/test_ops_evals.py`.

**Interfaces:**
- `ops.evals.CHEAPEST`, `ops.evals.conductor_argv(agent: str, turn: str, *, model: str | None, session: str | None) -> list[str]`, `ops.evals.parse_turn(agent: str, stdout: str) -> tuple[str | None, str]` (session id and reply text; claude `session_id`/`result`, agy `conversation_id`/`response`, codex `thread.started.thread_id`/last `agent_message`).
- `@dataclass ops.evals.EvalRun(name: str, agent: str, passed: bool, failure: str, work: Path)`.
- `ops.evals.run_scenario(name: str, scenario: EvalScenario, agent: str, *, work: Path, model: str | None, baseline: bool = False, source: Path | None = None) -> EvalRun`: `work/home/.harness` and `work/repo` (git repo on `main` with `files`, one commit); `harness init`; `settings` written to the defaults and project SETTINGS.md; setup steps (`save` keeps the first 8-hex word of stdout; a failing step fails the run `setup step N failed: <stderr tail>`); unless `baseline`, `ops.skills.install([agent], root=repo, source=source)` (in process); each turn filled and run with `run_process` (log `work/turn-<n>.out`), resuming the session; afterwards SIGTERM the process groups of every worker record in the store; then the expectations, first failure wins: `journal has no <type>`, `journal has <type>`, `plans: N, expected M` / `at least M`, `plan <id>: <field> is <v>, expected <w>`, `MEMORY.md lacks "<text>"`, `DECISIONS.md lacks "<text>"`, `the reply lacks "<text>"`; a turn's CLI error or timeout fails the run `turn N <timed out|exit E>: <stderr tail>`.

- [ ] Tests with the fake CLIs (each queued reply's `shell` runs real `harness` commands in the scratch repo): `test_a_scenario_passes_when_the_conductor_does_the_work` (claude: turn 1 runs `harness plan new …`; expectations met; argv has the conductor flags and `/to-plan …`; cwd is the scratch repo; `.claude/skills/` holds the installed skills), `test_later_turns_resume_the_session`, `test_each_failed_expectation_is_named` (parametrized), `test_setup_saves_ids_for_later_steps`, `test_baseline_runs_install_no_skills`, `test_agy_conductors_run_sandboxed_without_prompts`, `test_a_hanging_turn_times_out` (fake `sleep`, `timeout_s=1`); run FAIL; implement; run PASS; commit `feat: run eval scenarios headless`.

### Task 3: `harness skills eval` and `make evals`

**Files:** Modify `src/super_harness/ops/evals.py` (`run_evals`), `src/super_harness/cli.py`, `Makefile` (`evals: uv run harness skills eval --all`); Test `tests/test_cli_skills.py`; Create `evals/README.md` (format of a scenario).

**Interfaces:** `ops.evals.run_evals(skill: str | None, *, agents: Sequence[str] | None, model: str | None, baseline: bool, root: Path = EVALS_DIR, keep: Path | None = None) -> list[EvalRun]`: agents default to every usable one (detected); a named agent that is missing or signed out → `NeedsSetup`; runs in a temporary folder unless `keep`. CLI `harness skills eval [SKILL] [--all] [--agent A,…] [--model M] [--baseline] [--dir D] [--keep D] [--json]`: one line per run (§4); exit 1 on a failure.

- [ ] Tests: `test_cli_eval_prints_one_line_per_run` (a tmp `evals/probe/one.yaml`, fake claude), `test_cli_eval_needs_the_named_agent` (agy hidden → exit 4); run FAIL; implement; run PASS; commit `feat: harness skills eval`.

### Task 4: Live probe scenario, docs and review

**Files:** Create `tests/live/test_live_evals.py`: a tmp skill `probe-plan` (one step: `harness plan new --mode direct --title Probe` with a heredoc prompt), passed as `source`, run on claude and agy; module docs (`model`, `ops`, `cli`), `docs/architecture.md`, `docs/conventions/skills.md` (eval format).

- [ ] Write the live test; run it with `-m live` (claude and agy pass); docs; `make check`; commit `test: live eval probe`; review the M2 diff, fix Critical/Important test first, ledger minors.
