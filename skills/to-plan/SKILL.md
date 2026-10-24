---
name: to-plan
description: Use when the user runs /to-plan with a feature, change or project to plan without being questioned first.
disable-model-invocation: true
metadata: {source: super-harness}
---
# Plan it without questions

You write the plan; harness stores it and has another agent review it. Read with your file tools (read, search, list); use the shell only for the `harness` commands below, each as its own call with nothing chained before or after it. Never edit the repo's files or the `.harness` store yourself.

0. Run `harness --version`. If it does not print `super-harness <version>`, say "Install super-harness first: uv tool install git+https://github.com/normatov07/super-harness" and stop.
1. Run `harness context` and keep what it says about the user and the project.
2. Start the plan with the user's request, word for word:

   ```
   harness plan new --mode direct --title "<short title>" <<'EOF'
   <the user's request, verbatim>
   EOF
   ```

   It prints `plan <id> draft`; keep the id.
3. Read the code, docs and memory the request touches. Decide what the request leaves open yourself; each such call becomes one Assumptions line: the decision, the default you chose, why.
4. Save the plan, one `##` heading per section:

   ```
   harness plan save <id> <<'EOF'
   ## Goal
   <1-3 lines: the outcome and why>
   ## Assumptions
   ## Scope
   ## Out of scope
   ## Design
   <modules, interfaces, data; no code>
   ## Acceptance
   - [ ] <checkable criterion>
   ## Test seams
   ## Risks
   EOF
   ```

   It prints `plan <id> draft, N sections`.
5. Run `harness plan review <id>` with a 10-minute shell timeout; on exit 3, run it again. It prints `plan <id> round r: pass|fail, N findings`, then the findings.
6. Show the user the verdict and every finding, then ask: approve, edit or reject? Wait for the answer.
7. Act on it:
   - edit: change the sections, then repeat steps 4 and 5;
   - approve: `harness plan approve <id>`; when it exits 5 because the review failed, add `--skip-review` only because the user said to approve;
   - reject: `harness plan reject <id> --why "<the user's reason>"`.

Done when `harness plan show <id>` prints `status: approved` or `status: rejected`.
