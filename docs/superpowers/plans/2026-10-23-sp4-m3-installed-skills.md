# SP4 M3: Installed Skills Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans and superpowers:writing-skills. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The five installed skills (`harness-memory`, `to-plan`, `to-plan-with-grill`, `to-ticket`, `to-loop`), each proven by an eval scenario that fails without it and passes with it on claude and agy.

**Architecture:** Each skill is `skills/<name>/SKILL.md` (plus `references/` where named); each scenario is `evals/<name>/<scenario>.yaml`. The eval runner prefills `{agent}`, `{model}` and `{cli}` (`<agent>/<model>`, or the agent alone) so scenarios can put workers and the plan reviewer on the conductor's own cheap model.

**Spec:** `docs/superpowers/specs/2026-10-23-sp4-skills-design.md` (decisions 8, 9, 11–17), system spec §8.1 (each skill's steps) and §8.3 (writing standard).

## Global Constraints

- Lint-clean (`harness skills lint`): "Use when" descriptions within 500 characters that never summarise the steps; at most 80 lines and 400 words; step 0 runs `harness --version` and prints the install line otherwise; every `harness` command mentioned exists.
- User skills set `disable-model-invocation: true`; all carry `metadata: {source: super-harness}`.
- Stdin through `harness … <<'EOF'` heredocs; `harness wait` and `harness plan review` get a 10-minute shell timeout and are rerun on exit 3.
- RED: `harness skills eval <skill> --baseline` fails, its failure recorded in the scenario's `notes:`. GREEN: `harness skills eval <skill>` passes on claude and agy. REFACTOR: loopholes seen in transcripts get closed and re-run.
- Evals run on claude `haiku` and agy `gemini-3.8-flash-low`; they spend quota, so each skill gets one scenario.

## Tasks

### Task 1: Runner placeholders for the conductor's own CLI
- [ ] Test `test_settings_and_turns_get_the_agent_placeholders` (settings `plan.reviewer: {cli}` lands as `plan.reviewer: claude/haiku`; codex without a model gives `{cli}` = `codex`); run FAIL; prefill `values` with `agent`, `model`, `cli` before settings are written and fill `settings`; run PASS; docs (`evals/README.md`, ops README); commit `feat(evals): agent placeholders in scenarios`.

### Task 2: `harness-memory`
- [ ] Scenario `evals/harness-memory/preference.yaml`: one turn stating a lasting preference ("from now on I always want the diff, not prose"); expect `memory.write` and MEMORY.md holding "diff". RED (`--baseline`), record notes; write the skill (preference → `memory add --section`; decision → `memory add --decision`, run inside the project); GREEN on claude and agy; refactor; lint; commit `feat(skills): harness-memory`.

### Task 3: `to-plan`
- [ ] Scenario `evals/to-plan/direct.yaml`: `calc.py` in the repo; settings `plan.reviewer: {cli}`, `plan.review_max: 1`; turns `/to-plan Add an add(a, b) function to calc.py` then `Approve it.`; expect one plan, `mode: direct`, `status: approved`, journal `plan.created`, `plan.saved`, `plan.reviewed`, `plan.approved`. RED; skill (system spec §8.1 row: context → plan new → facts → sections with an `## Assumptions` line per unasked decision → plan save → plan review → findings → the user decides → plan approve, `--skip-review` only on the user's explicit override); GREEN; refactor; commit `feat(skills): to-plan`.

### Task 4: `to-plan-with-grill`
- [ ] Scenario `evals/to-plan-with-grill/grill.yaml`: turns `/to-plan-with-grill Add an add(a, b) function to calc.py`, `Take your recommended answers.`, `Yes, that is what I want.`, `Approve it.`; expect `mode: grill`, `status: approved`, `plan.saved`, `plan.reviewed`, `plan.approved`. RED; skill (grill rounds of at most `grill.round_size` questions, each with a recommended answer, the host's multiple-choice tool when it has one; restate; confirm; then as `to-plan`); GREEN; refactor; commit `feat(skills): to-plan-with-grill`.

### Task 5: `to-ticket`
- [ ] Scenario `evals/to-ticket/slices.yaml`: setup a direct plan with saved sections and `plan approve --skip-review`, saved as `{plan}`; turns `/to-ticket {plan}`, `Looks good, add them.`; expect tickets `min: 1`, journal `ticket.created`, plan `status: ticketed`. RED; skill plus `references/importance.md` (the rubric of system spec §8.1); GREEN; refactor; commit `feat(skills): to-ticket`.

### Task 6: `to-loop`
- [ ] Scenario `evals/to-loop/one-ticket.yaml`: settings put every agent on `{cli}`, `merge.mode: ask`, `project.test_cmd`; setup a quick plan and one simple ticket; turns `/to-loop`, `Merge it.`; `timeout_s: 2400`; expect the ticket `status: done/merged` and journal `ticket.merged`. RED; skill (doctor --quiet → next → run → wait with a 10-minute timeout, rerun on exit 3 → act on each event: loops and merges are the user's call, stalled tickets go back to planning → until nothing is runnable or the user stops); GREEN; refactor; commit `feat(skills): to-loop`.

### Task 7: Docs, acceptance and review
- [ ] README of `skills/`, module docs, `docs/architecture.md` (SP4 done), AGENTS.md status, SP4 spec §6 boxes, `make check`; `make evals` green on claude and agy; review the SP4 diff; commit `docs: SP4 complete`.
