---
name: plan
description: Use when the user runs /kengash:plan with a feature, change or project to plan without being questioned first.
disable-model-invocation: true
metadata: {source: kengash-ai}
---
# Plan it without questions

You write the plan; kengash stores it and has another agent review it. Read with your file tools (read, search, list); use the shell only for the `kengash` commands below, each as its own call with nothing chained before or after it. Never edit the repo's files or the `.kengash` store yourself.

`<scope>` below is `-p <project>` when the request names its project or folder (a path kept as typed), else empty. On exit 4 `not a kengash project`, ask whether to register that folder; only on yes, run `kengash init <folder>`, then retry.

0. Run `kengash --version`. If it does not print `kengash-ai <version>`, say "Install Kengash AI first: uv tool install kengash-ai" and stop.
1. Run `kengash context <scope>` and keep what it says about the user and the project.
2. Start the plan with the user's request, word for word:

   ```
   kengash plan new --mode direct --title "<short title>" <scope> <<'EOF'
   <the user's request, verbatim>
   EOF
   ```

   It prints `plan <id> draft`; keep the id.
3. Read the code, docs and memory the request touches. Decide what the request leaves open yourself; each such call becomes one Assumptions line: the decision, the default you chose, why.
4. Save the plan, one `##` heading per section:

   ```
   kengash plan save <id> <<'EOF'
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
5. Run `kengash plan review <id>` with a 10-minute shell timeout; on exit 3, run it again. It prints `plan <id> round r: pass|fail, N findings`, then the findings.
6. Show the user the verdict and every finding, then ask: approve, edit or reject? Wait for the answer.
7. Act on it:
   - edit: change the sections, then repeat steps 4 and 5;
   - approve: `kengash plan approve <id>`; when it exits 5 because the review failed, add `--skip-review` only because the user said to approve;
   - reject: `kengash plan reject <id> --why "<the user's reason>"`.

Done when `kengash plan show <id>` prints `status: approved` or `status: rejected`.
