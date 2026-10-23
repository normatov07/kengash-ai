# SP3 M2: Providers and Git Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Provider adapters for claude, codex, antigravity and shell behind one `Provider` protocol, fake CLIs that replay recorded fixtures, `gitops` for worktrees, commits, diffs, rebase and merge, and provider and trust checks in `harness doctor`.

**Architecture:** `model.steps` defines the step contract (`StepRequest`, `StepResult`, `Usage`, output schemas, `ProviderStatus`). `adapters` turns a request into one CLI call: a pure `command()` builds argv, a shared runner executes it in its own process group with a timeout, and a per-provider `parse()` maps raw output to a `StepResult`. `gitops` wraps git commands with typed results. Both import only `model`; `ops.providers` uses `adapters` for `doctor`. Workers and step execution arrive in M3.

**Tech Stack:** Python 3.12, pydantic 2, subprocess, git, pytest, import-linter, uv.

**Spec:** `docs/superpowers/specs/2026-10-22-sp3-engine-design.md` (§2 decisions 4, 5, 12, 13, 16, 19; §4; §8; §9; the `doctor` row of §10; §11), with system spec `2026-10-22-super-harness-design.md` §7.2 and §10.

## Global Constraints

- The spec is the contract; Task 1 changes it first where the 2026-10-23 live runs differ from it.
- A change to `src/super_harness/<module>` updates `docs/modules/<module>/README.md` in the same commit (`make docs` and the pre-commit hook enforce it).
- `adapters` and `gitops` import only `model`; they never touch the store (import contract in Tasks 3 and 8). `cli` imports only `ops` and `model`.
- Providers run only through their official binaries under the user's login: never read token files, never pass claude `--bare` or `--no-session-persistence`, never codex `--ephemeral`.
- Workers drop `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `CODEX_API_KEY`, `GEMINI_API_KEY`, `GOOGLE_API_KEY`, `CLAUDECODE` and `CLAUDE_CODE_ENTRYPOINT`, and set `HARNESS_AGENT=<role>`.
- No test ever runs a real provider CLI: an autouse fixture (Task 4) puts the fakes first on `PATH`.
- `ops` functions return dataclasses; `--json` prints everything.
- CI runs Ubuntu and macOS: process groups via `start_new_session=True`, never `setsid`; compare paths with `.resolve()`.
- Docs under `docs/` ≤ 150 lines; AGENTS.md ≤ 100 lines.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- One test: `uv run pytest tests/test_x.py::test_name`; everything: `make check`.

## Review Focus

1. Skill or prompt text that starts with `-` (skill files open with `---` frontmatter) must stay the prompt, never be read as a flag (Task 3 `positional`, tested per provider).
2. A prompt past the argument limit must fail as `crash` "prompt is N KiB; the limit is 120 KiB", not with an `OSError` traceback (Task 3).
3. A CLI that ignores SIGTERM at the timeout, or leaves a background child behind, must die with its process group within the grace period (Task 3).
4. CLI or test output that is not UTF-8 must decode with replacement characters, never raise (Task 3, shell).
5. An agent summary holding newlines or a fake `Harness-Ticket:` line must not forge trailers: the subject keeps its first line only (Task 8).

---

### Task 1: Record the live-run facts in the specs

Live runs on 2026-10-23 (claude 2.1.309, agy 1.4.5, scratch repo) showed:

- claude: `--permission-mode dontAsk` with the read tool set, and `acceptEdits --permission-prompts none` with `--resume`, both work in print mode; usage is per call.
- agy: `--disable-slash-commands` voids `--mode` (it prints `warning: --mode plan has no effect while slash command expansion is disabled.` and then edits files in a "plan" step). Without it, `--mode plan` blocks edits, and also denies terminal commands; a reviewer that tries one returns `status: SUCCESS` with `response: ""`, no `structured_output` and `denied_actions: [{"action": "command", ...}]`. Adding "read files with your file-viewing tools only; never run terminal commands" to the prompt makes plan-mode reviews succeed.
- agy: when a turn ends without schema JSON, `structured_output` repeats the previous turn's value even though `--json-schema` was passed; `response` holds the new text.
- agy: `usage` and `num_turns` are running totals for the conversation; `input_tokens` includes `cache_read_tokens`, and `output_tokens` includes thinking.

**Files:**
- Modify: `docs/superpowers/specs/2026-10-22-sp3-engine-design.md` (header line 7, §2 decision 4, §4 runtime tree, §8.1 table rows "isolation" and "output", §8.1 bullets, §10 `doctor` row)
- Modify: `docs/superpowers/specs/2026-10-22-super-harness-design.md` (§7.2 protocol block and `StepRequest`/`StepResult` lines)

- [ ] **Step 1: Edit the SP3 spec**

Make exactly these changes:
1. Header line 7: append "Permission rows re-checked on 2026-10-23 with claude 2.1.309 and agy 1.4.5 (M2)."
2. Decision 4: replace "and agy with `--disable-slash-commands`" with "; agy gets no isolation flag, because `--disable-slash-commands` voids `--mode`".
3. §4 runtime tree: add `├── trust.json                 digest of each repo's hook and MCP files doctor last reported`.
4. §8.1 table, isolation row, agy cell: `none (see below)`. Output row, agy cell: append "`denied_actions`; `usage` and `num_turns` are conversation totals".
5. Replace the bullet "agy repeats the previous turn's `structured_output` when a turn runs without a schema, so every agy turn passes the schema." with four bullets:
   - "agy repeats the previous turn's `structured_output` when a turn ends without schema JSON, even with the schema passed: the output counts only when `response` parses to the same JSON, else `schema`. Every agy turn still passes the schema."
   - "agy read-only steps run `--mode plan` and end the prompt with: `This is a read-only step: read files with your file-viewing tools only; never run terminal commands.` A turn with `denied_actions` and no output is `empty`, naming the denied actions."
   - "Token fields: `input` excludes cache reads (codex and agy include them in `input_tokens`, so the adapter subtracts); `output` includes thinking. agy reports conversation totals: the adapter subtracts the totals after the session's previous turn (`StepRequest.prior_usage`) and returns the new totals (`StepResult.total_usage`)."
   - "`allow_api_key` keeps only that provider's variables: claude `ANTHROPIC_API_KEY`; codex `OPENAI_API_KEY`, `CODEX_API_KEY`; antigravity `GEMINI_API_KEY`, `GOOGLE_API_KEY`. The bypass flag replaces the permission-profile flags for claude and codex; agy keeps `--mode`. Prompt and skill text never start with `-` in argv (a newline is prepended), and a prompt over 120 KiB fails as `crash` before the CLI starts. New claude sessions get their `--session-id` from harness, so a killed step can resume."
6. Replace the bullet starting "The permission rows for agy, agy's sign-in check, ..." with: "claude's `dontAsk`, `acceptEdits --permission-prompts none` and the agy rows were confirmed by live runs on 2026-10-23; the M4 live smoke re-checks them."
7. §10 `doctor` row, middle cell: "dead workers (M3); providers of enabled agents and the compactor that are missing, signed out or unsupported (a problem when a role has no usable fallback, else a warning); a claude login other than claude.ai (warning); repo hooks or MCP config (warning, once per repo until the files change)".

- [ ] **Step 2: Edit the system spec §7.2**

Change `attach_command(self, session_id: str, cwd: Path) -> list[str]` to `attach_command(self, session_id: str) -> list[str]` (the caller runs it in the worktree) and add `def recover_session(self, log: Path) -> str | None: ...  # session id from a killed step's raw output`. In the `StepRequest` line, replace "role skill path" with "role skill text, raw-output log path, the session's previous usage totals (agy)"; in the `StepResult` line, add "the session's new usage totals (agy)".

- [ ] **Step 3: Check and commit**

Run: `make docs`
Expected: no output.

```bash
git add docs/superpowers/specs/
git commit -m "docs: SP3 spec records the 2026-10-23 provider live runs"
```

---

### Task 2: Step contract in `model`

**Files:**
- Create: `src/super_harness/model/steps.py`
- Modify: `src/super_harness/model/__init__.py`
- Test: `tests/test_model_steps.py`
- Docs: `docs/modules/model/README.md`

**Interfaces:**
- Produces (all exported from `super_harness.model`):
  - `Profile = Literal["read_only", "edit_worktree"]`; `OutputKind = Literal["work", "review", "compact"]`; `ErrorKind = Literal["auth", "rate_limit", "timeout", "empty", "schema", "crash"]`.
  - `Usage(input: int = 0, output: int = 0, cache_read: int = 0, cache_write: int = 0, cost_usd: float | None = None)`, all ints ≥ 0; `Usage.tokens -> int` (input + output, decision 10); `Usage.minus(prior: Usage | None) -> Usage` (field-wise, floored at 0, `cost_usd` None).
  - `Finding(severity: Literal["high", "medium", "low"], file: str, line: int ≥ 0, issue: str, fix: str)`; `WorkOutput(summary: str, handoff: str)`; `ReviewOutput(verdict: Literal["pass", "fail"], summary: str, findings: list[Finding])`; `CompactOutput(text: str)`; `StepOutput = WorkOutput | ReviewOutput | CompactOutput`.
  - `OUTPUT_SCHEMAS: dict[OutputKind, dict[str, Any]]`, hand-written strict JSON schemas; `parse_output(kind: OutputKind, data: object) -> StepOutput` (raises `ValueError`; pydantic's `ValidationError` is one).
  - `StepRequest(role: str, cwd: Path, prompt: str, output: OutputKind, profile: Profile, timeout_s: int ≥ 1, log: Path, model: str | None = None, session_id: str | None = None, resume: bool = False, skill: str | None = None, test_cmd: str = "", lint_cmd: str = "", allow_api_key: bool = False, user_config: bool = False, bypass: bool = False, prior_usage: Usage | None = None)`; `resume=True` requires `session_id`.
  - `StepResult(session_id: str | None = None, output: StepOutput | None = None, text: str = "", usage: Usage = Usage(), total_usage: Usage | None = None, duration_s: float = 0.0, error: ErrorKind | None = None, retry_after: datetime | None = None, detail: str = "")` with computed field `ok: bool` (`error is None`).
  - `ProviderStatus(name: str, installed: bool, version: str | None = None, signed_in: bool = False, auth_method: str | None = None, hint: str = "")` with property `usable: bool` (`installed and signed_in`).

- [ ] **Step 1: Write the failing tests** in `tests/test_model_steps.py`

```python
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
    models = {"work": WorkOutput, "review": ReviewOutput, "compact": CompactOutput}
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
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_model_steps.py`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement `model/steps.py`** with the names and types in Interfaces. All models use `extra="forbid"`. Write `OUTPUT_SCHEMAS` by hand (plain dicts: `type`, `properties`, `required`, `additionalProperties: False`; `verdict` and `severity` use `enum`; `line` is `integer`). `ReviewOutput` raises "a failing verdict needs findings" in a model validator. `parse_output` calls `model_validate` on the kind's model. Export every name from `model/__init__.py`.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_model_steps.py && make type`
Expected: PASS, no type errors.

- [ ] **Step 5: Document and commit**

In `docs/modules/model/README.md` add an Interface bullet for the step contract (request, result, usage, outputs and their strict schemas, `ProviderStatus`) and a Changes line `2026-10-23: step contract and provider status (SP3 M2).`

```bash
git add src/super_harness/model/ tests/test_model_steps.py docs/modules/model/README.md
git commit -m "feat(model): step request, result, usage and output schemas"
```

---

### Task 3: `adapters` core: process runner, environment, shell, registry

**Files:**
- Create: `src/super_harness/adapters/__init__.py`, `adapters/process.py`, `adapters/env.py`, `adapters/base.py`, `adapters/shell.py`
- Modify: `pyproject.toml` (import contract)
- Test: `tests/test_adapters_core.py`
- Docs: `docs/modules/adapters/README.md` (new), `docs/architecture.md` (adapters row: "core and shell (SP3 M2)")

**Interfaces:**
- Consumes: Task 2 types.
- Produces:
  - `process.ProcessResult(exit_code: int, stdout: str, stderr: str, timed_out: bool, duration_s: float)` (dataclass).
  - `process.run_process(argv: list[str], *, cwd: Path, env: dict[str, str], timeout_s: float, log: Path, grace_s: float = 10.0) -> ProcessResult`: stdout to `log`, stderr to `log.with_suffix(".err")`, both read back with `errors="replace"`; parent dirs created.
  - `env.API_KEYS: dict[str, tuple[str, ...]]` = `{"claude": ("ANTHROPIC_API_KEY",), "codex": ("OPENAI_API_KEY", "CODEX_API_KEY"), "antigravity": ("GEMINI_API_KEY", "GOOGLE_API_KEY")}`; `env.worker_env(environ: Mapping[str, str], provider: str, role: str, *, allow_api_key: bool) -> dict[str, str]`.
  - `base.Provider` (Protocol): `name: str`; `detect() -> ProviderStatus`; `run(req: StepRequest) -> StepResult`; `attach_command(session_id: str) -> list[str]`; `recover_session(log: Path) -> str | None`.
  - `base.CliProvider`: class attributes `name`, `binary`, `install_hint`, `signin_hint`; subclasses implement `command(req) -> list[str]`, `parse(req, proc: ProcessResult) -> StepResult`, `signed_in() -> tuple[bool, str | None]` (signed in, auth method), `attach_command`; shared `run`, `detect`, and `recover_session` returning None.
  - `base.MAX_PROMPT_BYTES = 120 * 1024`; `base.positional(text: str) -> str` (prepends `"\n"` when `text` starts with `-`); `base.classify(text: str) -> ErrorKind` (`auth`, `rate_limit` or `crash`); `base.tail(text: str, lines: int = 20) -> str`; `base.schema_json(kind: OutputKind) -> str` (compact `json.dumps` of `OUTPUT_SCHEMAS[kind]`); `base.checked(kind, data) -> tuple[StepOutput | None, str]` (output, or None and the `schema` detail).
  - `shell.Shell` (implements `Provider`, `name = "shell"`).
  - `adapters.get(name: str, *, runtime: Path) -> Provider`: `claude`, `codex` (schemas in `runtime / "schemas"`), `antigravity`, `shell`; `gemini` raises `NeedsSetup("gemini is not supported yet; pick another provider in SETTINGS.md")`; anything else `UserError(f"unknown provider: {name}")`. Tasks 5–7 register their classes here.

- [ ] **Step 1: Write the failing tests** in `tests/test_adapters_core.py`

```python
def _request(tmp_path: Path, **fields: Any) -> StepRequest:
    base = {
        "role": "test-runner",
        "cwd": tmp_path,
        "prompt": "",
        "output": "review",
        "profile": "read_only",
        "timeout_s": 5,
        "log": tmp_path / "logs" / "t-1.out",
    }
    return StepRequest.model_validate(base | fields)


def test_run_process_writes_the_log_and_returns_output(tmp_path: Path) -> None:
    log = tmp_path / "logs" / "a-1.out"
    result = run_process(
        ["sh", "-c", "echo out; echo err >&2; exit 3"],
        cwd=tmp_path,
        env=dict(os.environ),
        timeout_s=5,
        log=log,
    )
    assert (result.exit_code, result.stdout, result.stderr, result.timed_out) == (
        3,
        "out\n",
        "err\n",
        False,
    )
    assert log.read_text() == "out\n" and log.with_suffix(".err").read_text() == "err\n"


def _gone(pid: int, within: float = 3.0) -> bool:
    """True once `pid` no longer exists; polls, because a killed child may linger as a zombie."""
    deadline = time.monotonic() + within
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.05)
    return False


def test_a_timeout_kills_the_whole_group_even_when_sigterm_is_ignored(tmp_path: Path) -> None:
    pid_file = tmp_path / "child.pid"
    script = f"trap '' TERM; sleep 30 & echo $! > {pid_file}; wait"
    started = time.monotonic()
    result = run_process(
        ["sh", "-c", script],
        cwd=tmp_path,
        env=dict(os.environ),
        timeout_s=1,
        log=tmp_path / "t.out",
        grace_s=1,
    )
    assert result.timed_out and time.monotonic() - started < 6
    assert _gone(int(pid_file.read_text()))


def test_background_children_die_when_the_cli_exits(tmp_path: Path) -> None:
    pid_file = tmp_path / "child.pid"
    run_process(
        ["sh", "-c", f"sleep 30 & echo $! > {pid_file}"],
        cwd=tmp_path,
        env=dict(os.environ),
        timeout_s=5,
        log=tmp_path / "b.out",
    )
    assert _gone(int(pid_file.read_text()))


def test_worker_env_drops_keys_and_conductor_markers() -> None:
    environ = {
        "PATH": "/bin",
        "ANTHROPIC_API_KEY": "a",
        "OPENAI_API_KEY": "o",
        "CODEX_API_KEY": "c",
        "GEMINI_API_KEY": "g",
        "GOOGLE_API_KEY": "k",
        "CLAUDECODE": "1",
        "CLAUDE_CODE_ENTRYPOINT": "cli",
    }
    assert worker_env(environ, "claude", "planner", allow_api_key=False) == {
        "PATH": "/bin",
        "HARNESS_AGENT": "planner",
    }
    kept = worker_env(environ, "codex", "implementer", allow_api_key=True)
    assert {k for k in kept if k.endswith("_API_KEY")} == {"OPENAI_API_KEY", "CODEX_API_KEY"}


def test_positional_prompts_never_look_like_flags() -> None:
    assert positional("---\nname: plan") == "\n---\nname: plan"
    assert positional("You are the planner") == "You are the planner"


def test_classify_reads_auth_and_rate_limit_text() -> None:
    assert classify("Invalid API key · Please run /login") == "auth"
    assert classify("Not logged in") == "auth"
    assert classify("You've hit your usage limit. Try again in 2 hours") == "rate_limit"
    assert classify("RESOURCE_EXHAUSTED: quota") == "rate_limit"
    assert classify("segfault") == "crash"


def test_shell_passes_on_exit_zero(tmp_path: Path) -> None:
    result = Shell().run(_request(tmp_path, test_cmd="echo ok"))
    assert result.ok and result.output == ReviewOutput(
        verdict="pass", summary="tests passed", findings=[]
    )


def test_shell_failure_keeps_the_last_20_lines_even_when_not_utf8(tmp_path: Path) -> None:
    script = "for i in $(seq 1 30); do echo line$i; done; printf '\\377\\376 bad'; exit 2"
    result = Shell().run(_request(tmp_path, test_cmd=script))
    assert isinstance(result.output, ReviewOutput) and result.output.verdict == "fail"
    assert result.output.summary == "tests failed (exit 2)"
    [finding] = result.output.findings
    assert finding.issue.splitlines()[0] == "line12" and "�" in finding.issue
    assert (finding.severity, finding.file, finding.line, finding.fix) == (
        "high",
        "",
        0,
        "make project.test_cmd pass",
    )


def test_shell_without_a_test_command_fails(tmp_path: Path) -> None:
    result = Shell().run(_request(tmp_path))
    assert (result.error, result.detail) == ("crash", "set project.test_cmd")


def test_shell_timeout(tmp_path: Path) -> None:
    result = Shell().run(_request(tmp_path, test_cmd="sleep 10", timeout_s=1))
    assert (result.error, result.detail) == ("timeout", "killed after 1 s")


def test_get_knows_the_providers(tmp_path: Path) -> None:
    assert get("shell", runtime=tmp_path).name == "shell"
    with pytest.raises(NeedsSetup, match="gemini is not supported yet"):
        get("gemini", runtime=tmp_path)
    with pytest.raises(UserError, match="unknown provider: cursor"):
        get("cursor", runtime=tmp_path)
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_adapters_core.py`
Expected: FAIL with `ModuleNotFoundError: super_harness.adapters`.

- [ ] **Step 3: Implement the runner, environment and helpers**

`run_process`: `subprocess.Popen(argv, cwd=cwd, env=env, stdin=DEVNULL, stdout=<log file>, stderr=<err file>, start_new_session=True)`; `wait(timeout_s)`; on `TimeoutExpired` send `SIGTERM` to the group, wait `grace_s`, then `SIGKILL` the group and wait. After any exit, `SIGTERM` the group once more so background children die (ignore `ProcessLookupError` and `PermissionError`). `exit_code` is the return code (negative for a signal). `classify` checks auth first: `(?i)not logged in|/login\b|invalid api key|unauthori[sz]ed|authenticat|sign in|\b40[13]\b`, then rate limits: `(?i)usage limit|rate limit|limit reached|too many requests|quota|resource_exhausted|\b429\b`.

`CliProvider.run(req)`, in order: prompt plus skill over `MAX_PROMPT_BYTES` → `StepResult(error="crash", detail=f"prompt is {size // 1024} KiB; the limit is 120 KiB")`; `shutil.which(self.binary)` is None → `crash`, `f"{self.binary} not found on PATH"`; run `self.command(req)` with `worker_env(os.environ, self.name, req.role, allow_api_key=req.allow_api_key)`, timeout `req.timeout_s`, log `req.log`; timed out → `error="timeout"`, `detail=f"killed after {req.timeout_s} s"`, `session_id=req.session_id`; else `self.parse(req, proc)`; set `duration_s` from the process. `CliProvider.detect()`: not on PATH → `installed=False, hint=self.install_hint`; else version is the first `\d+\.\d+(\.\d+)?` in `<binary> --version` output (20 s timeout), then `signed_in()`; signed out → `hint=self.signin_hint`. Run detection commands with `subprocess.run(..., capture_output=True, text=True, errors="replace", timeout=20)`.

`checked(kind, data)`: `parse_output`, or `(None, f"output does not match the {kind} schema: {first line of the error}")`.

- [ ] **Step 4: Implement `Shell`**

`run`: empty `test_cmd` → `crash` "set project.test_cmd"; else `run_process(["sh", "-c", req.test_cmd], ...)` with `worker_env(..., "shell", req.role, allow_api_key=False)`; timeout as in `CliProvider.run`; exit 0 → pass "tests passed"; else one finding whose `issue` is `tail(stdout + stderr)` (or `f"exit {code}"` when empty), summary `f"tests failed (exit {code})"`. `detect` → installed and signed in; `attach_command` raises `UserError("shell steps have no session")`; `recover_session` → None.

- [ ] **Step 5: Add the import contract** to `pyproject.toml`

```toml
[[tool.importlinter.contracts]]
name = "Adapters and gitops never touch the store: they import only model"
type = "forbidden"
source_modules = ["super_harness.adapters"]
forbidden_modules = [
    "super_harness.cli",
    "super_harness.ops",
    "super_harness.memory",
    "super_harness.journal",
    "super_harness.settings",
    "super_harness.store",
    "super_harness.workflow",
    "super_harness.scheduler",
]
```

- [ ] **Step 6: Run the tests and the checks**

Run: `uv run pytest tests/test_adapters_core.py && make lint type`
Expected: PASS; lint-imports reports every contract kept.

- [ ] **Step 7: Document and commit**

Write `docs/modules/adapters/README.md` (Purpose, Interface, Invariants, Changes; same shape as `docs/modules/workflow/README.md`): one call per step, process group and timeout rules, environment scrubbing, error kinds, never-used flags, `get`. Update the adapters row in `docs/architecture.md`.

```bash
git add src/super_harness/adapters/ tests/test_adapters_core.py pyproject.toml docs/modules/adapters/ docs/architecture.md
git commit -m "feat(adapters): process runner, worker environment and shell provider"
```

---

### Task 4: Fake CLIs and recorded fixtures

**Files:**
- Create: `tests/fakes/fake_cli.py`, `tests/fakes/bin/claude`, `tests/fakes/bin/codex`, `tests/fakes/bin/agy` (executable)
- Create: `tests/fakes/fixtures/README.md` and the fixture files listed in Step 3
- Modify: `tests/conftest.py` (autouse `fake_clis` fixture)
- Test: `tests/test_fakes.py`

**Interfaces:**
- Produces, in `tests/conftest.py`: autouse fixture `fake_clis -> FakeClis` with
  - `queue(cli: str, *, fixture: str | None = None, stdout: str = "", stderr: str = "", exit: int = 0, edits: dict[str, str] | None = None, sleep: float = 0) -> None`: replies are used in queue order;
  - `calls(cli: str) -> list[dict[str, Any]]`: `{"argv": [...], "cwd": str, "env": {name: value}}` per call, `argv` without the binary;
  - `fixture(name: str) -> str`: text of `tests/fakes/fixtures/<name>`; `fixture_json(name: str) -> Any`;
  - `hide(cli: str)`: removes it from `PATH`; `sign_out(cli: str)`: its status command reports signed out; `auth_method(method: str)`: claude's `auth status` reports that `authMethod`.
  - `cli` is the binary name: `claude`, `codex` or `agy`.
- The fake, for argv `--version` → `2.1.309 (Claude Code)` / `codex-cli 0.161.0` / `1.4.5`; claude `auth status ...` → `{"loggedIn": true, "authMethod": "claude.ai", "apiProvider": "firstParty"}` (signed out: `{"loggedIn": false}`, exit 1); codex `login status` → `Logged in using ChatGPT` (signed out: `Not logged in`, exit 1); agy `models` → `gemini-3-pro` (signed out: `not signed in`, exit 1). Any other argv pops the next queued reply; with none queued it prints `fake <cli>: no reply queued` to stderr and exits 97. Every call is recorded first; edits are written relative to the working directory before stdout is printed.

- [ ] **Step 1: Write the failing tests** in `tests/test_fakes.py`

```python
def test_the_fake_replays_records_and_edits(
    fake_clis: FakeClis, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    fake_clis.queue("claude", fixture="claude/review_new.json", edits={"src/a.py": "x = 2\n"})
    result = subprocess.run(["claude", "-p", "hi"], cwd=tmp_path, capture_output=True, text=True)
    assert (result.returncode, result.stdout) == (0, fake_clis.fixture("claude/review_new.json"))
    assert (tmp_path / "src" / "a.py").read_text() == "x = 2\n"
    [call] = fake_clis.calls("claude")
    assert call["argv"] == ["-p", "hi"] and Path(call["cwd"]).resolve() == tmp_path.resolve()
    assert call["env"]["OPENAI_API_KEY"] == "sk-test"


def test_status_commands_answer_without_a_queue(fake_clis: FakeClis) -> None:
    assert subprocess.run(["codex", "login", "status"], capture_output=True).returncode == 0
    fake_clis.sign_out("codex")
    assert subprocess.run(["codex", "login", "status"], capture_output=True).returncode == 1
    unqueued = subprocess.run(["agy", "-p", "x"], capture_output=True, text=True)
    assert (unqueued.returncode, unqueued.stderr) == (97, "fake agy: no reply queued\n")


def test_hidden_clis_are_off_the_path(fake_clis: FakeClis) -> None:
    assert shutil.which("agy") is not None
    fake_clis.hide("agy")
    assert shutil.which("agy") is None
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_fakes.py`
Expected: FAIL: fixture `fake_clis` not found.

- [ ] **Step 3: Record the fixtures**

Record in a scratch git repo holding `a.py` with `x=1`, outside this repo, with `env -u CLAUDECODE -u CLAUDE_CODE_ENTRYPOINT`. `$REVIEW` and `$WORK` are `OUTPUT_SCHEMAS["review"]` and `["work"]` as compact JSON; `$READ` is the claude read tool set from Task 5. Never record `claude auth status`: it prints the account's email and organisation.

```bash
claude -p "Review a.py. Fail it with one low finding: variable name x is unclear." --output-format json --json-schema "$REVIEW" --session-id "$(uuidgen)" --model haiku --setting-sources project,local --strict-mcp-config --permission-mode dontAsk --allowedTools $READ > claude/review_new.json
claude -p "Loop 2, step implement: rename x in a.py to retry_count. Do not commit." --resume <that id> --output-format json --json-schema "$WORK" --model haiku --setting-sources project,local --strict-mcp-config --permission-mode acceptEdits --permission-prompts none --allowedTools $READ > claude/work_resume.json
agy -p "Review a.py. Fail it with one low finding: variable name x is unclear.

This is a read-only step: read files with your file-viewing tools only; never run terminal commands." --output-format json --json-schema "$REVIEW" --mode plan > agy/review_new.json
agy -p "Loop 2, step implement: rename x in a.py to retry_count. Do not commit." --conversation <its conversation_id> --output-format json --json-schema "$WORK" --mode accept-edits > agy/work_resume.json
agy -p "Reply now without using any tools: summary ok, handoff ok." --conversation <same id> --output-format json --json-schema "$WORK" --mode plan > agy/stale_output.json
agy -p "Edit a.py now: change x=1 to retry_count=1. Then report." --output-format json --json-schema "$WORK" --mode plan > agy/denied.json
```

Check each recording shows what its name says (`stale_output.json`: `response` is not the JSON of `structured_output`; `denied.json`: `denied_actions` and no `structured_output`). Write the synthetic fixtures by hand:
- `claude/auth_error.json`: the recorded `review_new.json` with `is_error: true`, `api_error_status: 401`, `result: "Invalid API key · Please run /login"`, no `structured_output`.
- `claude/usage_limit.json`: same with `api_error_status: 429`, `result: "Claude AI usage limit reached|1793001600"`.
- `codex/review_new.jsonl`, from the Codex non-interactive docs: `{"type":"thread.started","thread_id":"0199a213-81c0-7800-8aa1-bbab2a035a53"}`, `{"type":"turn.started"}`, an `item.completed` `reasoning` item, an `item.completed` `agent_message` whose `text` is `{"verdict":"pass","summary":"No issues found.","findings":[]}`, and `{"type":"turn.completed","usage":{"input_tokens":24763,"cached_input_tokens":24448,"output_tokens":122}}`.
- `codex/work_resume.jsonl`: the same thread id; one `agent_message` with work JSON; usage `{"input_tokens":30100,"cached_input_tokens":28000,"output_tokens":410}`.
- `codex/usage_limit.jsonl`: `thread.started`, `turn.started`, `{"type":"error","message":"You've hit your usage limit. Try again in 2 hours 5 minutes."}`, `{"type":"turn.failed","error":{"message":"You've hit your usage limit. Try again in 2 hours 5 minutes."}}`.
- `agy/error.json`: `{"conversation_id":"","status":"ERROR","response":"authentication required: sign in to Antigravity","duration_seconds":0.4,"num_turns":0}`.

`tests/fakes/fixtures/README.md` lists each file as recorded (with date and CLI version) or synthetic (with its source), and repeats the recording commands.

- [ ] **Step 4: Implement the fake and the fixture**

`tests/fakes/bin/<cli>` is `#!/bin/sh` + `exec "$HARNESS_FAKE_PYTHON" "$(dirname "$0")/../fake_cli.py" <cli> "$@"`. `fake_cli.py` (stdlib only, typed for mypy) keeps per-CLI state under `$HARNESS_FAKE_DIR/<cli>/`: `queue/NNNN.json` replies (lowest first), `calls.jsonl`, a `signed_out` flag file, and claude's optional `auth_method` file. It records the env values of the five API-key variables, `CLAUDECODE`, `CLAUDE_CODE_ENTRYPOINT` and `HARNESS_AGENT` that are set. The autouse `fake_clis` fixture symlinks the three scripts into `tmp_path / "fake-bin"`, sets `HARNESS_FAKE_DIR`, `HARNESS_FAKE_PYTHON=sys.executable` and `PATH` to `fake-bin`, git's directory, `/usr/bin` and `/bin`, in that order.

- [ ] **Step 5: Run the whole suite**

Run: `make test`
Expected: PASS, including every earlier test with the fakes first on `PATH`.

- [ ] **Step 6: Commit**

```bash
git add tests/fakes/ tests/conftest.py tests/test_fakes.py
git commit -m "test: fake claude, codex and agy CLIs with recorded fixtures"
```

---

### Task 5: Claude adapter

**Files:**
- Create: `src/super_harness/adapters/claude.py`
- Modify: `src/super_harness/adapters/__init__.py` (register)
- Test: `tests/test_adapters_claude.py`
- Docs: `docs/modules/adapters/README.md`

**Interfaces:**
- Consumes: `CliProvider`, `positional`, `classify`, `schema_json`, `checked`, `tail` (Task 3); `FakeClis` (Task 4).
- Produces: `Claude(CliProvider)`, `name = "claude"`, `binary = "claude"`; `READ_TOOLS = ("Read", "Grep", "Glob", "Bash(git diff:*)", "Bash(git log:*)", "Bash(git show:*)", "Bash(git status:*)")`.

argv, in this order (`--allowedTools` takes several values, so the profile goes last):

```
new:    claude -p <positional(prompt)> --output-format json --json-schema <schema_json>
        --session-id <req.session_id or uuid4> [--model M] [--append-system-prompt <positional(skill)>]
        [isolation] [bypass | profile]
resume: claude -p <positional(prompt)> --resume <id> --output-format json --json-schema <schema_json>
        [--model M] [isolation] [bypass | profile]
isolation (unless user_config): --setting-sources project,local --strict-mcp-config
bypass: --dangerously-skip-permissions
read_only: --permission-mode dontAsk --allowedTools *READ_TOOLS
edit_worktree: --permission-mode acceptEdits --permission-prompts none --allowedTools *READ_TOOLS
               then "Bash(<test_cmd>:*)" and "Bash(<lint_cmd>:*)" for each non-empty command
```

Parsing: empty stdout with exit 0 → `empty` "no output"; stdout that is not a JSON object → `crash` with `tail(stderr or stdout)` (or `classify` of that text when it names auth or a rate limit). From the object: `session_id` (else `req.session_id`); usage `input=input_tokens`, `output=output_tokens`, `cache_read=cache_read_input_tokens`, `cache_write=cache_creation_input_tokens`, `cost_usd=total_cost_usd`; `text=result`. `is_error` or a non-zero exit: `api_error_status` 401/403 → `auth`; 429 → `rate_limit`; else `classify(result)`; `retry_after` from `\|(\d{10})\b` in `result` as a UTC time; `detail=tail(result)`. Otherwise `structured_output` missing → `schema` "no structured output"; else `checked(req.output, structured_output)`. `signed_in()`: `claude auth status --json` → (`loggedIn`, `authMethod`); unparseable output → (False, None). `attach_command(id)` → `["claude", "--resume", id]`. Hints: install "install Claude Code, then run `claude` once to sign in"; sign in "run `claude` and sign in with /login".

- [ ] **Step 1: Write the failing tests** in `tests/test_adapters_claude.py`

```python
def _request(
    tmp_path: Path, **fields: Any
) -> StepRequest: ...  # as in Task 3, role "code-reviewer"


def test_new_read_only_session_flags(tmp_path: Path) -> None:
    argv = Claude().command(
        _request(
            tmp_path, prompt="Review", session_id="s-1", model="haiku", skill="---\nname: review"
        )
    )
    assert argv[:3] == ["claude", "-p", "Review"]
    assert argv[argv.index("--session-id") + 1] == "s-1"
    assert argv[argv.index("--append-system-prompt") + 1] == "\n---\nname: review"
    assert json.loads(argv[argv.index("--json-schema") + 1]) == OUTPUT_SCHEMAS["review"]
    assert argv[-10:] == ["--permission-mode", "dontAsk", "--allowedTools", *READ_TOOLS]
    assert {"--setting-sources", "--strict-mcp-config", "--model"} <= set(argv)


def test_resumed_edit_session_flags(tmp_path: Path) -> None:
    argv = Claude().command(
        _request(
            tmp_path,
            prompt="-fix it",
            output="work",
            resume=True,
            session_id="s-1",
            profile="edit_worktree",
            test_cmd="uv run pytest -q",
            lint_cmd="",
        )
    )
    assert argv[:3] == ["claude", "-p", "\n-fix it"]
    assert argv[argv.index("--resume") + 1] == "s-1" and "--session-id" not in argv
    assert argv[argv.index("--permission-mode") + 1] == "acceptEdits"
    assert argv[argv.index("--permission-prompts") + 1] == "none"
    assert argv[-1] == "Bash(uv run pytest -q:*)"


def test_user_config_and_bypass(tmp_path: Path) -> None:
    argv = Claude().command(_request(tmp_path, prompt="p", user_config=True, bypass=True))
    assert "--setting-sources" not in argv and "--permission-mode" not in argv
    assert argv[-1] == "--dangerously-skip-permissions"


def test_commands_never_use_forbidden_flags(tmp_path: Path) -> None:
    for profile in ("read_only", "edit_worktree"):
        argv = Claude().command(_request(tmp_path, prompt="p", profile=profile))
        assert not {"--bare", "--no-session-persistence"} & set(argv)


def test_a_recorded_review_parses(fake_clis: FakeClis, tmp_path: Path) -> None:
    raw = fake_clis.fixture_json("claude/review_new.json")
    fake_clis.queue("claude", fixture="claude/review_new.json")
    result = Claude().run(_request(tmp_path, prompt="Review", session_id=raw["session_id"]))
    assert result.ok and result.session_id == raw["session_id"]
    assert isinstance(result.output, ReviewOutput) and result.output.verdict == "fail"
    assert result.usage == Usage(
        input=raw["usage"]["input_tokens"],
        output=raw["usage"]["output_tokens"],
        cache_read=raw["usage"]["cache_read_input_tokens"],
        cache_write=raw["usage"]["cache_creation_input_tokens"],
        cost_usd=raw["total_cost_usd"],
    )
    [call] = fake_clis.calls("claude")
    assert Path(call["cwd"]).resolve() == tmp_path.resolve()
    assert (tmp_path / "logs" / "t-1.out").read_text() == fake_clis.fixture(
        "claude/review_new.json"
    )


def test_a_recorded_resume_parses_work(fake_clis: FakeClis, tmp_path: Path) -> None:
    raw = fake_clis.fixture_json("claude/work_resume.json")
    fake_clis.queue("claude", fixture="claude/work_resume.json")
    result = Claude().run(
        _request(
            tmp_path,
            prompt="Loop 2",
            output="work",
            resume=True,
            session_id=raw["session_id"],
            profile="edit_worktree",
        )
    )
    assert isinstance(result.output, WorkOutput) and result.session_id == raw["session_id"]


def test_error_kinds(fake_clis: FakeClis, tmp_path: Path) -> None:
    fake_clis.queue("claude", fixture="claude/auth_error.json")
    assert Claude().run(_request(tmp_path, prompt="p")).error == "auth"
    fake_clis.queue("claude", fixture="claude/usage_limit.json")
    limited = Claude().run(_request(tmp_path, prompt="p"))
    assert limited.error == "rate_limit"
    assert limited.retry_after == datetime.fromtimestamp(1793001600, UTC)
    fake_clis.queue("claude", stdout="")
    assert Claude().run(_request(tmp_path, prompt="p")).error == "empty"
    raw = fake_clis.fixture_json("claude/review_new.json")
    raw["structured_output"] = {"verdict": "fail", "summary": "s", "findings": []}
    fake_clis.queue("claude", stdout=json.dumps(raw))
    assert Claude().run(_request(tmp_path, prompt="p")).error == "schema"
    fake_clis.queue("claude", stdout="", stderr="boom", exit=1)
    crashed = Claude().run(_request(tmp_path, prompt="p"))
    assert (crashed.error, crashed.detail) == ("crash", "boom")


def test_timeouts_keep_the_session(fake_clis: FakeClis, tmp_path: Path) -> None:
    fake_clis.queue("claude", fixture="claude/review_new.json", sleep=5)
    result = Claude().run(_request(tmp_path, prompt="p", session_id="s-1", timeout_s=1))
    assert (result.error, result.session_id) == ("timeout", "s-1")


def test_environment_is_scrubbed(
    fake_clis: FakeClis, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant")
    monkeypatch.setenv("CLAUDECODE", "1")
    fake_clis.queue("claude", fixture="claude/review_new.json")
    Claude().run(_request(tmp_path, prompt="p"))
    [call] = fake_clis.calls("claude")
    assert call["env"] == {"HARNESS_AGENT": "code-reviewer"}


def test_oversized_prompts_fail_before_the_cli_starts(fake_clis: FakeClis, tmp_path: Path) -> None:
    result = Claude().run(_request(tmp_path, prompt="x" * 200_000))
    assert (result.error, result.detail) == ("crash", "prompt is 195 KiB; the limit is 120 KiB")
    assert fake_clis.calls("claude") == []


def test_detect_and_attach(fake_clis: FakeClis) -> None:
    status = Claude().detect()
    assert (status.installed, status.version, status.signed_in, status.auth_method) == (
        True,
        "2.1.309",
        True,
        "claude.ai",
    )
    fake_clis.sign_out("claude")
    assert Claude().detect().hint == "run `claude` and sign in with /login"
    fake_clis.hide("claude")
    assert Claude().detect().installed is False
    assert Claude().attach_command("s-1") == ["claude", "--resume", "s-1"]
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_adapters_claude.py`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `Claude`** per the argv block and parsing rules above; register it in `adapters.get`.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_adapters_claude.py && make lint type`
Expected: PASS.

- [ ] **Step 5: Document and commit** (adapters README: claude flags, parsing, signed-in check)

```bash
git add src/super_harness/adapters/ tests/test_adapters_claude.py docs/modules/adapters/README.md
git commit -m "feat(adapters): claude provider"
```

---

### Task 6: Codex adapter

**Files:**
- Create: `src/super_harness/adapters/codex.py`
- Modify: `src/super_harness/adapters/__init__.py`
- Test: `tests/test_adapters_codex.py`
- Docs: `docs/modules/adapters/README.md`

**Interfaces:**
- Produces: `Codex(CliProvider)` with `__init__(self, schemas: Path)`, `name = "codex"`, `binary = "codex"`; `Codex.schema_file(kind: OutputKind) -> Path` writes `schemas / f"{kind}.json"` (atomic replace, only when the content differs) and returns it.

argv:

```
new:    codex exec --json --output-schema <file> (-s <sandbox> | bypass) [-m M] [isolation] <positional(prompt)>
resume: codex exec resume --json --output-schema <file> (-c sandbox_mode="<sandbox>" | bypass) [-m M] [isolation]
        <id> <positional(prompt)>
sandbox: read_only → read-only; edit_worktree → workspace-write
isolation (unless user_config): --ignore-user-config
bypass: --dangerously-bypass-approvals-and-sandbox
skill (new sessions): prompt becomes f"{skill}\n\n{prompt}"
```

Parsing (JSONL; lines that are not JSON objects are skipped): `thread.started` → `session_id = thread_id` (else `req.session_id`); the last `item.completed` whose `item.type` is `agent_message` holds the output JSON in `item.text`; each `turn.completed` adds `input = input_tokens - cached_input_tokens`, `output = output_tokens`, `cache_read = cached_input_tokens`; an `error` event's `message` or a `turn.failed` event's `error.message` → `classify(message)` with `detail=tail(message)`. No agent message: `empty` "no output" on exit 0, else `crash` with `tail(stderr)` (`classify`d). Agent text that is not JSON, or fails the schema → `schema`. `signed_in()`: `codex login status` exit code 0 → (True, None). `recover_session(log)`: the first `thread.started` id in the file, else None. `attach_command(id)` → `["codex", "resume", id]`. Hints: install "install the Codex CLI (npm i -g @openai/codex), then run `codex login`"; sign in "run `codex login`".

- [ ] **Step 1: Write the failing tests** in `tests/test_adapters_codex.py`

```python
def test_new_session_flags(tmp_path: Path) -> None:
    codex = Codex(tmp_path / "schemas")
    argv = codex.command(_request(tmp_path, prompt="Review", skill="Be terse.", model="gpt-5"))
    assert argv[:5] == [
        "codex",
        "exec",
        "--json",
        "--output-schema",
        str(tmp_path / "schemas" / "review.json"),
    ]
    assert argv[argv.index("-s") + 1] == "read-only" and argv[argv.index("-m") + 1] == "gpt-5"
    assert "--ignore-user-config" in argv and argv[-1] == "Be terse.\n\nReview"
    assert (
        json.loads((tmp_path / "schemas" / "review.json").read_text()) == OUTPUT_SCHEMAS["review"]
    )


def test_resume_takes_the_sandbox_as_config(tmp_path: Path) -> None:
    argv = Codex(tmp_path).command(
        _request(
            tmp_path,
            prompt="Loop 2",
            output="work",
            resume=True,
            session_id="t-1",
            profile="edit_worktree",
        )
    )
    assert argv[:3] == ["codex", "exec", "resume"]
    assert argv[argv.index("-c") + 1] == 'sandbox_mode="workspace-write"'
    assert "-s" not in argv and "-C" not in argv and argv[-2:] == ["t-1", "Loop 2"]


def test_bypass_replaces_the_sandbox_and_no_ephemeral(tmp_path: Path) -> None:
    argv = Codex(tmp_path).command(_request(tmp_path, prompt="p", bypass=True, user_config=True))
    assert "--dangerously-bypass-approvals-and-sandbox" in argv
    assert not {"-s", "--ignore-user-config", "--ephemeral"} & set(argv)


def test_a_review_parses(fake_clis: FakeClis, tmp_path: Path) -> None:
    fake_clis.queue("codex", fixture="codex/review_new.jsonl")
    result = Codex(tmp_path).run(_request(tmp_path, prompt="Review"))
    assert result.ok and result.session_id == "0199a213-81c0-7800-8aa1-bbab2a035a53"
    assert result.output == ReviewOutput(verdict="pass", summary="No issues found.", findings=[])
    assert result.usage == Usage(input=315, output=122, cache_read=24448)


def test_usage_limits_and_missing_output(fake_clis: FakeClis, tmp_path: Path) -> None:
    fake_clis.queue("codex", fixture="codex/usage_limit.jsonl")
    assert Codex(tmp_path).run(_request(tmp_path, prompt="p")).error == "rate_limit"
    fake_clis.queue("codex", stdout='{"type":"thread.started","thread_id":"t"}\n')
    assert Codex(tmp_path).run(_request(tmp_path, prompt="p")).error == "empty"
    fake_clis.queue("codex", stdout="", stderr="Not logged in", exit=1)
    assert Codex(tmp_path).run(_request(tmp_path, prompt="p")).error == "auth"


def test_a_killed_step_recovers_its_thread(tmp_path: Path, fake_clis: FakeClis) -> None:
    log = tmp_path / "k-1.out"
    log.write_text(fake_clis.fixture("codex/review_new.jsonl").splitlines()[0] + "\n")
    assert Codex(tmp_path).recover_session(log) == "0199a213-81c0-7800-8aa1-bbab2a035a53"
    assert Codex(tmp_path).recover_session(tmp_path / "none.out") is None


def test_detect(fake_clis: FakeClis, tmp_path: Path) -> None:
    assert Codex(tmp_path).detect().version == "0.161.0"
    fake_clis.sign_out("codex")
    assert Codex(tmp_path).detect().hint == "run `codex login`"
```

`input=315` is 24763 − 24448.

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_adapters_codex.py`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `Codex`**; register it in `adapters.get` with `runtime / "schemas"`.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_adapters_codex.py && make lint type`
Expected: PASS.

- [ ] **Step 5: Document and commit**

```bash
git add src/super_harness/adapters/ tests/test_adapters_codex.py docs/modules/adapters/README.md
git commit -m "feat(adapters): codex provider"
```

---

### Task 7: Antigravity adapter

**Files:**
- Create: `src/super_harness/adapters/antigravity.py`
- Modify: `src/super_harness/adapters/__init__.py`
- Test: `tests/test_adapters_antigravity.py`
- Docs: `docs/modules/adapters/README.md`

**Interfaces:**
- Produces: `Antigravity(CliProvider)`, `name = "antigravity"`, `binary = "agy"`; `READ_ONLY_LINE = "This is a read-only step: read files with your file-viewing tools only; never run terminal commands."`

argv (no isolation flag; `user_config` has no effect):

```
new:    agy -p <positional(text)> --output-format json --json-schema <schema_json> [--model M] --mode <mode> [bypass]
resume: agy -p <positional(text)> --conversation <id> --output-format json --json-schema <schema_json>
        [--model M] --mode <mode> [bypass]
mode: read_only → plan; edit_worktree → accept-edits
bypass: --dangerously-skip-permissions (keeps --mode)
text: skill + "\n\n" + prompt for new sessions; read_only appends "\n\n" + READ_ONLY_LINE
```

Parsing: empty stdout with exit 0 → `empty` "no output"; not a JSON object → `crash` (`classify`d `tail(stderr or stdout)`). From the object: `session_id = conversation_id or req.session_id`; totals `input = input_tokens - cache_read_tokens`, `output = output_tokens`, `cache_read = cache_read_tokens`; `usage = totals.minus(req.prior_usage)`, `total_usage = totals`; `text = response`. `status` other than `SUCCESS` → `classify(response + "\n" + stderr)`, `detail=tail(response or stderr)`. No `structured_output` → `empty`, detail "no output" or `f"no output; denied: {', '.join(display_name of each denied action)}"`. `json.loads(response)` fails or differs from `structured_output` → `schema` "agy repeated the previous turn's output". Else `checked(req.output, structured_output)`. `signed_in()`: `agy models` exit code 0 → (True, None). `attach_command(id)` → `["agy", "--conversation", id]`. Hints: install "install the Antigravity CLI (agy), then run `agy` once to sign in"; sign in "run `agy` and sign in".

- [ ] **Step 1: Write the failing tests** in `tests/test_adapters_antigravity.py`

```python
def test_read_only_steps_run_in_plan_mode_with_the_read_only_line(tmp_path: Path) -> None:
    argv = Antigravity().command(_request(tmp_path, prompt="Review", skill="---\nrole"))
    assert argv[:3] == ["agy", "-p", f"\n---\nrole\n\nReview\n\n{READ_ONLY_LINE}"]
    assert argv[argv.index("--mode") + 1] == "plan"
    assert "--disable-slash-commands" not in argv


def test_resumed_edits_keep_the_schema(tmp_path: Path) -> None:
    argv = Antigravity().command(
        _request(
            tmp_path,
            prompt="Loop 2",
            output="work",
            resume=True,
            session_id="c-1",
            profile="edit_worktree",
            bypass=True,
        )
    )
    assert argv[argv.index("--conversation") + 1] == "c-1"
    assert json.loads(argv[argv.index("--json-schema") + 1]) == OUTPUT_SCHEMAS["work"]
    assert argv[argv.index("--mode") + 1] == "accept-edits"
    assert argv[-1] == "--dangerously-skip-permissions" and READ_ONLY_LINE not in argv[2]


def test_a_recorded_review_parses(fake_clis: FakeClis, tmp_path: Path) -> None:
    raw = fake_clis.fixture_json("agy/review_new.json")
    fake_clis.queue("agy", fixture="agy/review_new.json")
    result = Antigravity().run(_request(tmp_path, prompt="Review"))
    assert result.ok and result.session_id == raw["conversation_id"]
    assert isinstance(result.output, ReviewOutput) and result.output.verdict == "fail"
    usage = raw["usage"]
    assert result.usage == Usage(
        input=usage["input_tokens"] - usage["cache_read_tokens"],
        output=usage["output_tokens"],
        cache_read=usage["cache_read_tokens"],
    )
    assert result.total_usage == result.usage


def test_resumed_usage_is_the_difference_of_totals(fake_clis: FakeClis, tmp_path: Path) -> None:
    first, second = (
        fake_clis.fixture_json(f"agy/{name}.json") for name in ("review_new", "work_resume")
    )
    fake_clis.queue("agy", fixture="agy/review_new.json")
    prior = Antigravity().run(_request(tmp_path, prompt="Review")).total_usage
    fake_clis.queue("agy", fixture="agy/work_resume.json")
    result = Antigravity().run(
        _request(
            tmp_path,
            prompt="Loop 2",
            output="work",
            resume=True,
            session_id=first["conversation_id"],
            profile="edit_worktree",
            prior_usage=prior,
        )
    )
    assert isinstance(result.output, WorkOutput)
    assert result.usage.output == second["usage"]["output_tokens"] - first["usage"]["output_tokens"]


def test_stale_and_denied_turns(fake_clis: FakeClis, tmp_path: Path) -> None:
    fake_clis.queue("agy", fixture="agy/stale_output.json")
    stale = Antigravity().run(_request(tmp_path, prompt="p", output="work"))
    assert (stale.error, stale.detail) == ("schema", "agy repeated the previous turn's output")
    fake_clis.queue("agy", fixture="agy/denied.json")
    denied = Antigravity().run(_request(tmp_path, prompt="p", output="work"))
    assert (denied.error, denied.detail) == ("empty", "no output; denied: RunCommand")
    fake_clis.queue("agy", fixture="agy/error.json")
    assert Antigravity().run(_request(tmp_path, prompt="p")).error == "auth"


def test_detect(fake_clis: FakeClis) -> None:
    assert (Antigravity().detect().version, Antigravity().detect().signed_in) == ("1.4.5", True)
    fake_clis.sign_out("agy")
    assert Antigravity().detect().hint == "run `agy` and sign in"
    assert Antigravity().attach_command("c-1") == ["agy", "--conversation", "c-1"]
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_adapters_antigravity.py`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `Antigravity`**; register it in `adapters.get`.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_adapters_antigravity.py && make lint type`
Expected: PASS.

- [ ] **Step 5: Document and commit**

```bash
git add src/super_harness/adapters/ tests/test_adapters_antigravity.py docs/modules/adapters/README.md
git commit -m "feat(adapters): antigravity provider"
```

---

### Task 8: `gitops` worktrees, commits and diffs

**Files:**
- Create: `src/super_harness/gitops.py`
- Modify: `pyproject.toml` (add `super_harness.gitops` to the Task 3 contract's `source_modules`)
- Test: `tests/test_gitops.py`
- Docs: `docs/modules/gitops/README.md` (new), `docs/architecture.md` (gitops row)

**Interfaces:**
- Produces:
  - `GitError(UserError)`: message `f"git {subcommand} failed: {last stderr line}"`; `CommitFailed(GitError)` with `output: str` (git's whole stdout and stderr, hook output included).
  - `Worktree(path: Path, branch: str, created: bool)`; `FileChange(path: str, added: int | None, removed: int | None)` (None for binary files); frozen dataclasses.
  - `ensure_worktree(repo: Path, path: Path, branch: str, base: str) -> Worktree`: `git worktree prune`; reuse `path` when it is a worktree on `branch` (`created=False`); a `path` that exists otherwise → `GitError(f"{path} exists and is not the worktree of {branch}")`; re-attach an existing branch with `git worktree add <path> <branch>`; else `git worktree add -b <branch> <path> <base>`.
  - `head(cwd: Path) -> str`; `current_branch(cwd: Path) -> str | None` (None when detached); `is_clean(cwd: Path) -> bool` (tracked files only: `git status --porcelain --untracked-files=no`); `reset_soft(cwd: Path, commit: str) -> None`.
  - `commit_all(cwd: Path, subject: str, trailers: dict[str, str]) -> str | None`: `git add -A`; nothing staged → None; else commit with message `<first line of subject>\n\n<Key: value lines>` (the subject alone when `trailers` is empty) through `git commit -q -F -`, return the new sha. Uses the user's identity, signing and hooks; no `-c` overrides, no `--no-verify`. Failure → `CommitFailed`.
  - `diff(cwd: Path, base: str, *, stat: bool = False) -> str` (`git diff [--stat] <base>...HEAD`); `numstat(cwd: Path, base: str) -> list[FileChange]`.

- [ ] **Step 1: Write the failing tests** in `tests/test_gitops.py`

Isolate git config for the module (identity without `-c`, and no signing or hooks from the developer's own config):

```python
@pytest.fixture(autouse=True)
def git_identity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = tmp_path / "gitconfig"
    config.write_text("[user]\n\tname = Dev\n\temail = dev@example.com\n")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")


TRAILERS = {
    "Harness-Ticket": "7b55e0c1-3d42-4ab9-9f07-c81e2a6d5f10",
    "Harness-Step": "implement",
    "Harness-Loop": "2",
    "Harness-Agent": "implementer",
    "Harness-Model": "codex/default",
}


def _worktree(repo: Path, tmp_path: Path) -> Worktree:
    return ensure_worktree(repo, tmp_path / "wt" / "hrn-7b55e0c1", "hrn/7b55e0c1", "main")


def test_worktrees_are_created_reused_and_reattached(repo: Path, tmp_path: Path) -> None:
    first = _worktree(repo, tmp_path)
    assert first.created and current_branch(first.path) == "hrn/7b55e0c1"
    assert _worktree(repo, tmp_path).created is False
    shutil.rmtree(first.path)
    again = _worktree(repo, tmp_path)
    assert again.created and current_branch(again.path) == "hrn/7b55e0c1"


def test_a_foreign_folder_blocks_the_worktree(repo: Path, tmp_path: Path) -> None:
    (tmp_path / "wt" / "hrn-7b55e0c1").mkdir(parents=True)
    with pytest.raises(GitError, match="is not the worktree of hrn/7b55e0c1"):
        _worktree(repo, tmp_path)


def test_commit_all_writes_trailers(
    repo: Path, tmp_path: Path, run_git: Callable[..., str]
) -> None:
    wt = _worktree(repo, tmp_path).path
    assert commit_all(wt, "nothing", TRAILERS) is None
    (wt / "retry.py").write_text("retries = 3\n")
    sha = commit_all(wt, "hrn(7b55e0c1): loop 2 implement: retry with backoff", TRAILERS)
    assert sha == head(wt)
    body = run_git(wt, "log", "-1", "--format=%s%n%(trailers:only,unfold)")
    assert body.splitlines()[0] == "hrn(7b55e0c1): loop 2 implement: retry with backoff"
    assert "Harness-Model: codex/default" in body
    assert run_git(wt, "log", "-1", "--format=%an").strip() == "Dev"


def test_a_summary_cannot_forge_trailers(
    repo: Path, tmp_path: Path, run_git: Callable[..., str]
) -> None:
    wt = _worktree(repo, tmp_path).path
    (wt / "a.py").write_text("a = 1\n")
    commit_all(wt, "fix\n\nHarness-Ticket: 00000000-0000-4000-8000-000000000000", TRAILERS)
    trailers = run_git(wt, "log", "-1", "--format=%(trailers:only,unfold)")
    assert "00000000" not in trailers and run_git(wt, "log", "-1", "--format=%s").strip() == "fix"


def test_a_failing_hook_returns_its_output(repo: Path, tmp_path: Path) -> None:
    wt = _worktree(repo, tmp_path).path
    hook = repo / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\necho 'lint: missing docstring'\nexit 1\n")
    hook.chmod(0o755)
    (wt / "a.py").write_text("a = 1\n")
    with pytest.raises(CommitFailed) as caught:
        commit_all(wt, "add a", TRAILERS)
    assert "lint: missing docstring" in caught.value.output


def test_reset_soft_and_diffs(repo: Path, tmp_path: Path) -> None:
    wt = _worktree(repo, tmp_path).path
    start = head(wt)
    (wt / "a.py").write_text("a = 1\nb = 2\n")
    (wt / "blob.bin").write_bytes(b"\x00\x01")
    commit_all(wt, "agent commit", {})
    reset_soft(wt, start)
    assert head(wt) == start and not is_clean(wt)
    commit_all(wt, "harness commit", TRAILERS)
    assert sorted(numstat(wt, "main"), key=lambda c: c.path) == [
        FileChange("a.py", 2, 0),
        FileChange("blob.bin", None, None),
    ]
    assert "a.py" in diff(wt, "main", stat=True) and "+b = 2" in diff(wt, "main")
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_gitops.py`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement `gitops.py`** with one private runner `_git(cwd: Path, *args: str, input: str | None = None) -> str` (`subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, errors="replace")`, `GitError` on a non-zero exit) and the functions in Interfaces. Add `super_harness.gitops` to the contract's `source_modules`.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_gitops.py && make lint type`
Expected: PASS.

- [ ] **Step 5: Document and commit**

Write `docs/modules/gitops/README.md` (worktree rules, commit message shape, the user's identity and hooks, typed errors) and update the gitops row in `docs/architecture.md`.

```bash
git add src/super_harness/gitops.py tests/test_gitops.py pyproject.toml docs/modules/gitops/ docs/architecture.md
git commit -m "feat(gitops): worktrees, commits with trailers and diffs"
```

---

### Task 9: `gitops` rebase, merge, cleanup and ticket history

**Files:**
- Modify: `src/super_harness/gitops.py`
- Test: `tests/test_gitops.py`
- Docs: `docs/modules/gitops/README.md`

**Interfaces:**
- Consumes: Task 8.
- Produces:
  - `Commit(sha: str, subject: str, trailers: dict[str, str], files: list[FileChange])` (frozen dataclass).
  - `rebase(cwd: Path, base: str) -> list[str]`: `[]` on success; on conflict, the sorted conflicted paths (`git diff --name-only --diff-filter=U`) after `git rebase --abort`; a failure without conflicted paths → `GitError`.
  - `merge_ff(repo: Path, branch: str, base: str) -> int`: refuses with `GitError(f"main working tree is on {current or 'a detached HEAD'}, not {base}")` or `GitError("main working tree has uncommitted changes")`; counts `git rev-list --count <base>..<branch>`, runs `git merge --ff-only -q <branch>`, returns the count.
  - `remove_worktree(repo: Path, path: Path, branch: str) -> None`: `git worktree remove --force <path>` when it exists, `git worktree prune`, then `git branch -D <branch>` when the branch exists.
  - `ticket_commits(repo: Path, ticket_uuid: str, ref: str) -> list[Commit]`: oldest first; `git log --reverse --fixed-strings --grep "Harness-Ticket: <uuid>" --format=%H <ref>`, then per commit its subject, trailers (`%(trailers:only,unfold)`, split on the first `": "`) and numstat.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_gitops.py`)

```python
def test_rebase_onto_a_moved_base(repo: Path, tmp_path: Path) -> None:
    wt = _worktree(repo, tmp_path).path
    (wt / "a.py").write_text("a = 1\n")
    commit_all(wt, "add a", TRAILERS)
    (repo / "b.py").write_text("b = 1\n")
    commit_all(repo, "add b on main", {})
    assert rebase(wt, "main") == []
    assert (wt / "b.py").exists()


def test_a_rebase_conflict_aborts_and_names_files(repo: Path, tmp_path: Path) -> None:
    wt = _worktree(repo, tmp_path).path
    (wt / "README.md").write_text("ticket\n")
    commit_all(wt, "edit readme", TRAILERS)
    (repo / "README.md").write_text("main\n")
    commit_all(repo, "edit readme on main", {})
    before = head(wt)
    assert rebase(wt, "main") == ["README.md"]
    assert head(wt) == before and current_branch(wt) == "hrn/7b55e0c1"


def test_merge_fast_forwards_then_cleanup(repo: Path, tmp_path: Path) -> None:
    worktree = _worktree(repo, tmp_path)
    for name in ("a.py", "b.py"):
        (worktree.path / name).write_text("x = 1\n")
        commit_all(worktree.path, f"add {name}", TRAILERS)
    assert merge_ff(repo, "hrn/7b55e0c1", "main") == 2
    remove_worktree(repo, worktree.path, "hrn/7b55e0c1")
    assert not worktree.path.exists() and (repo / "b.py").exists()
    commits = ticket_commits(repo, TRAILERS["Harness-Ticket"], "main")
    assert [c.subject for c in commits] == ["add a.py", "add b.py"]
    assert commits[0].trailers == TRAILERS and commits[0].files == [FileChange("a.py", 1, 0)]


def test_merge_refuses_a_dirty_or_moved_main_tree(
    repo: Path, tmp_path: Path, run_git: Callable[..., str]
) -> None:
    _worktree(repo, tmp_path)
    (repo / "README.md").write_text("local edit\n")
    with pytest.raises(GitError, match="main working tree has uncommitted changes"):
        merge_ff(repo, "hrn/7b55e0c1", "main")
    run_git(repo, "checkout", "-q", "README.md")
    run_git(repo, "checkout", "-q", "-b", "spike")
    with pytest.raises(GitError, match="main working tree is on spike, not main"):
        merge_ff(repo, "hrn/7b55e0c1", "main")
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_gitops.py`
Expected: the four new tests FAIL with `ImportError`.

- [ ] **Step 3: Implement** the four functions and `Commit` per Interfaces.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_gitops.py && make lint type`
Expected: PASS.

- [ ] **Step 5: Document and commit**

```bash
git add src/super_harness/gitops.py tests/test_gitops.py docs/modules/gitops/README.md
git commit -m "feat(gitops): rebase, fast-forward merge, cleanup and ticket history"
```

---

### Task 10: Provider and trust checks in `doctor`

**Files:**
- Create: `src/super_harness/ops/providers.py`
- Modify: `src/super_harness/ops/projects.py` (`Problem.warning`, call the checks), `src/super_harness/cli.py` (warnings never fail `doctor`)
- Modify: `src/super_harness/model/runtime.py`, `src/super_harness/model/__init__.py` (`Trust`), `src/super_harness/store/paths.py` (`trust`), `src/super_harness/store/runtime.py` (`load_trust`, `save_trust`)
- Test: `tests/test_ops_providers.py`, `tests/test_cli_projects.py`
- Docs: `docs/modules/ops/README.md`, `docs/modules/cli/README.md`, `docs/modules/model/README.md`, `docs/modules/store/README.md`

**Interfaces:**
- Consumes: `adapters.get(name, runtime=)`, `Provider.detect()`, `ProviderStatus` (Tasks 2–7).
- Produces:
  - `Trust(seen: dict[str, str] = {})` (runtime model); `StorePaths.trust` → `runtime/trust.json`; `load_trust(paths) -> Trust`, `save_trust(paths, trust) -> None`.
  - `ops.providers.ProviderCheck(provider: str, users: list[str], blocking: bool, message: str)` (dataclass).
  - `ops.providers.check_providers(paths: StorePaths) -> list[ProviderCheck]`: only providers that need attention, in `PROVIDERS` order.
  - `ops.providers.trust_notice(paths: StorePaths, slug: str, repo: Path) -> str | None`.
  - `ops.projects.Problem` gains `warning: bool = False`.

Rules for `check_providers`:
- Scopes: the defaults scope and every registered project (`settings.load`). Users: each enabled agent whose `cli` is not `shell` (label: the role), each provider in its `fallback` (same label), and `memory.compactor` (label `compactor`); deduplicated, in first-seen order.
- Each used provider is detected once with `adapters.get(name, runtime=paths.runtime).detect()`; `gemini` is never detected.
- Messages, exactly: `f"{p}: not installed; used by {users}; {hint}"`, `f"{p}: signed out; used by {users}; {hint}"`, `f"gemini: not supported yet; used by {users}; pick another provider in SETTINGS.md"`, and for a usable claude whose `auth_method` is not `claude.ai` while the defaults scope has `providers.claude.allow_api_key: false`: `f"claude: signed in with {method}, not a claude.ai subscription; workers will bill it"` (always a warning). `{users}` is comma-joined.
- `blocking` is true when some user that names the provider as its `cli` (or the compactor) has no usable provider among its `cli` and fallbacks.

Rules for `trust_notice`: found items are `.claude/settings.json hooks` (that file parses as JSON with a non-empty `hooks` key) and `.mcp.json` (exists). None found → forget the slug and return None. Otherwise the digest is the SHA-256 of the found files' bytes in that order; when it equals `Trust.seen[slug]` return None, else record it and return `f"repo ships {' and '.join(found)}; workers run them without a trust prompt"`.

`projects.doctor` appends `Problem(check.message, None, warning=not check.blocking)` per provider check after the project checks, and `Problem(notice, slug, warning=True)` per project with a notice (only when its repo exists). The CLI prints warnings as `[<slug>: ]warning: <message>`, prints `ok: N projects` only when there are no problems at all, and exits 1 only for problems that are neither fixed nor warnings.

- [ ] **Step 1: Write the failing tests** in `tests/test_ops_providers.py`

```python
def test_every_provider_usable_reports_nothing(
    registered_repo: Path, store_paths: StorePaths
) -> None:
    assert check_providers(store_paths) == []


def test_a_missing_provider_without_fallback_blocks(
    registered_repo: Path, store_paths: StorePaths, fake_clis: FakeClis
) -> None:
    fake_clis.hide("codex")
    [check] = check_providers(store_paths)
    assert check.blocking and check.message == (
        "codex: not installed; used by plan-reviewer, implementer; "
        "install the Codex CLI (npm i -g @openai/codex), then run `codex login`"
    )


def test_a_fallback_only_use_warns(
    registered_repo: Path, store_paths: StorePaths, fake_clis: FakeClis
) -> None:
    fake_clis.sign_out("claude")
    write_settings(
        store_paths,
        "agents.planner.cli: codex\nagents.code-reviewer.cli: codex\n"
        "agents.security-reviewer.cli: codex\nmemory.compactor: codex\n",
    )
    [check] = check_providers(store_paths)
    assert not check.blocking
    assert (
        check.message
        == "claude: signed out; used by implementer; run `claude` and sign in with /login"
    )


def test_disabled_agents_are_not_checked(
    registered_repo: Path, store_paths: StorePaths, fake_clis: FakeClis
) -> None:
    fake_clis.hide("agy")
    assert check_providers(store_paths) == []


def test_gemini_is_unsupported(registered_repo: Path, store_paths: StorePaths) -> None:
    write_settings(
        store_paths,
        "agents.doc-writer: {on: true, cli: gemini, skill: sync-docs}\n",
        slugs=("payments-api",),
    )
    [check] = check_providers(store_paths)
    assert check.blocking and check.message == (
        "gemini: not supported yet; used by doc-writer; pick another provider in SETTINGS.md"
    )


def test_a_claude_login_without_subscription_warns(
    registered_repo: Path, store_paths: StorePaths, fake_clis: FakeClis
) -> None:
    fake_clis.auth_method("console")
    [check] = check_providers(store_paths)
    assert not check.blocking and check.message == (
        "claude: signed in with console, not a claude.ai subscription; workers will bill it"
    )
    write_settings(store_paths, "providers.claude.allow_api_key: true\n", slugs=(None,))
    assert check_providers(store_paths) == []


def test_trust_notice_shows_once_per_change(registered_repo: Path, store_paths: StorePaths) -> None:
    assert trust_notice(store_paths, "payments-api", registered_repo) is None
    (registered_repo / ".mcp.json").write_text('{"mcpServers": {}}')
    settings = registered_repo / ".claude" / "settings.json"
    settings.parent.mkdir()
    settings.write_text('{"hooks": {"PostToolUse": []}}')
    assert trust_notice(store_paths, "payments-api", registered_repo) == (
        "repo ships .claude/settings.json hooks and .mcp.json; workers run them without a trust prompt"
    )
    assert trust_notice(store_paths, "payments-api", registered_repo) is None
    (registered_repo / ".mcp.json").write_text('{"mcpServers": {"x": {}}}')
    assert trust_notice(store_paths, "payments-api", registered_repo) is not None
```

`write_settings(paths: StorePaths, text: str, slugs: tuple[str | None, ...] = (None, "payments-api")) -> None` is a helper in this test file: it replaces each named scope's SETTINGS.md (`paths.defaults / "SETTINGS.md"` for None, else the project's) with `text`. Settings layers merge dotted keys over the package defaults, so an override-only file is valid; both scopes are replaced by default because a project's SETTINGS.md starts as a full copy of the defaults.

Append to `tests/test_cli_projects.py`:

```python
def test_doctor_warnings_do_not_fail(store_paths: StorePaths, repo: Path) -> None:
    runner.invoke(app, ["init", str(repo)])
    (repo / ".mcp.json").write_text("{}")
    result = runner.invoke(app, ["doctor"])
    assert (result.exit_code, result.stdout) == (
        0,
        "payments-api: warning: repo ships .mcp.json; workers run them without a trust prompt\n",
    )
    assert runner.invoke(app, ["doctor"]).stdout == "ok: 1 project\n"


def test_doctor_fails_on_a_blocking_provider(
    store_paths: StorePaths, repo: Path, fake_clis: FakeClis
) -> None:
    runner.invoke(app, ["init", str(repo)])
    fake_clis.hide("codex")
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 1 and result.stdout.startswith("codex: not installed;")
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_ops_providers.py tests/test_cli_projects.py`
Expected: FAIL with `ModuleNotFoundError: super_harness.ops.providers`.

- [ ] **Step 3: Implement** `Trust`, the trust paths and store functions, `ops/providers.py`, `Problem.warning`, the doctor calls and the CLI output, per the rules above.

- [ ] **Step 4: Run the whole suite**

Run: `make check`
Expected: PASS, with the earlier doctor tests unchanged (the fakes report every provider signed in).

- [ ] **Step 5: Document and commit**

Update the four module READMEs: `ops` (providers module, doctor additions), `cli` (warning lines and exit code), `model` (`Trust`), `store` (`runtime/trust.json`).

```bash
git add src/super_harness/ tests/test_ops_providers.py tests/test_cli_projects.py docs/modules/
git commit -m "feat(ops): doctor checks providers and repo trust"
```

---

### Task 11: Docs status and critical review

**Files:**
- Modify: `docs/architecture.md` (adapters and gitops rows "built (SP3 M2)", ops row adds `providers`, SP3 row "M1 and M2 built; M3 workers and controls next"), `AGENTS.md` (status line: sub-project 3 in progress with M2 built)

- [ ] **Step 1: Update the status lines** in `docs/architecture.md` and `AGENTS.md` as listed above.

- [ ] **Step 2: Run everything**

Run: `make check`
Expected: PASS with no output beyond pytest's summary.

- [ ] **Step 3: Review every M2 change against the spec**

Walk SP3 spec §2 (decisions 4, 5, 12, 13, 16, 19), §4, §8, §9 and §11, and system spec §7.2 and §10, against `git diff <M1 head>...HEAD`. Confirm: every §8.1 cell has a test asserting it; no adapter or gitops import outside `model`; the five Review Focus inputs are tested; error kinds match §8.1; fixture README marks synthetic files. Fix gaps in place, each with a test.

- [ ] **Step 4: Commit**

```bash
git add docs/architecture.md AGENTS.md
git commit -m "docs: SP3 M2 built"
```
