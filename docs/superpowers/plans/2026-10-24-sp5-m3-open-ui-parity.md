# SP5 M3: `open-ui` and Parity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `/open-ui` opens the UI from any agent, proven by an eval on claude and agy; the canvas parity checklist is closed; SP5 is documented as done.

**Architecture:** The eval runner learns UI scenarios: a `ui` expectation (the sandbox store's UI server is running), a no-op `BROWSER` so no window opens, and stopping any UI server a run leaves. The skill is the smallest text that makes the scenario pass, written test first per `docs/conventions/skills.md`.

**Tech Stack:** as SP4 (skills, `harness skills eval`); `make evals` spends quota and runs only the new scenario here.

**Spec:** `docs/superpowers/specs/2026-10-23-sp5-ui-design.md` (§1 row M3, decision 13, §4, §5); `docs/superpowers/specs/2026-10-23-sp4-skills-design.md` (skill rules, decision 1).

## Global Constraints

- Skill rules: "Use when" description ≤ 500 characters, ≤ 80 lines and ≤ 400 words, step 0 checks `harness --version`, `disable-model-invocation: true`, only `harness` commands, each its own shell call.
- An eval never opens a browser window or leaves a server running on the user's machine.
- Module docs change with modules; commits end with the Co-Authored-By line.

## Review Focus

1. A run whose conductor starts the UI and then fails a later turn still stops the server (Task 1).
2. A UI started outside the sandbox (the user's own) is never touched by the runner (Task 1).
3. `/open-ui` when the UI already runs prints the same link instead of starting a second server (Task 2, reuse is `ui_server`'s).
4. The missing-extra path (exit 4) asks before installing anything (Task 2).

---

### Task 1: UI scenarios in the eval runner
**Files:** Modify `model/evals.py` (`Expect.ui: bool`), `ops/evals.py` (`check` fails "the UI server is not running" without a live `runtime/ui.json`; `_env` sets `BROWSER=true`; `run_scenario` stops the sandbox's UI server in an outer `finally`), `evals/README.md`; Test `tests/test_ops_evals.py`.
- [ ] Tests: `check` with `ui: true` fails on an empty store and passes with a record whose pid is alive; a scenario whose fake conductor starts a detached `sleep` recorded as the UI leaves no process behind; `_env` has `BROWSER=true`. FAIL, implement, PASS; commit `feat(evals): UI scenarios`.

### Task 2: `open-ui` skill
**Files:** Create `evals/open-ui/opens.yaml` (turn `/open-ui`; expect `ui: true`, reply holds `http://127.0.0.1:`, `clean: true`), `skills/open-ui/SKILL.md`; Modify `skills/README.md`.
- [ ] RED: `harness skills eval open-ui --agent claude,antigravity --baseline`, record the failure in the scenario's `notes`. GREEN: skill steps: version check; `harness ui open`; on exit 4 show the install line, ask, run `uv tool install --force 'super-harness[ui] @ git+https://github.com/normatov07/super-harness'` only on yes, then `harness ui open` again; give the user the printed link. Run the eval on claude and agy until green; `harness skills lint`; commit `feat(skills): open-ui`.

### Task 3: Parity checklist and SP5 acceptance
- [ ] Walk spec §4 row by row against the built screens (the canvas parity pass of 2026-10-24); add the nav "Agents n/m" count note as built; tick §5 acceptance boxes with evidence (tests, screenshots, evals); commit `docs: SP5 parity checklist closed`.

### Task 4: Docs and review
- [ ] README (UI section: `harness ui open`, the `[ui]` extra, screens), `docs/architecture.md` (SP5 done), AGENTS.md status (5 of 5), module docs; `make check`; review the M3 diff against this plan's Review Focus; commit `docs: SP5 complete`.
