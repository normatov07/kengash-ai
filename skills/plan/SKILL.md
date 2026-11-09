---
name: plan
description: Use when the user runs /kengash:plan with a feature, change or project to plan without being questioned first.
disable-model-invocation: true
metadata: {source: kengash-ai}
---
# Plan it without questions

You write the plan; another agent reviews it. Read with your file tools; use the shell only for the `kengash` commands below, each as its own call, nothing chained. Never edit the repo's files or the `.kengash` store yourself.

`<scope>` below is `-p <project>` when the request names its project or folder (a path kept as typed), else empty. On exit 4 `not a kengash project`, ask whether to register that folder; only on yes, run `kengash init <folder>`, then retry.

0. Run `kengash --version`. If it does not print `kengash-ai <version>`, say "Install Kengash AI first: uv tool install kengash-ai" and stop.
1. Run `kengash context <scope>` and keep what it says.
2. Start the plan with the user's request, word for word:

   ```
   kengash plan new --mode direct --title "<short title>" <scope> <<'EOF'
   <the user's request, verbatim>
   EOF
   ```

   It prints `plan <id> draft`; keep the id.
3. Read the code, docs and memory the request touches. Decide what the request leaves open yourself; each call becomes one Assumptions line: the default you chose and why.
4. Save the plan, one `##` heading per section; one Lasting decisions line `- <decision>. why: <reason>.` per choice later work must follow, or `none`:

   ```
   kengash plan save <id> <<'EOF'
   ## Goal
   <1-3 lines: the outcome and why>
   ## Assumptions
   ## Lasting decisions
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
5. Run `kengash plan review <id>` with a 10-minute shell timeout; on exit 3, run it again.
6. Show the user the verdict and every finding; ask: approve, edit or reject? Wait for the answer.
7. Act on it:
   - edit: change the sections, then repeat steps 4 and 5;
   - approve: `kengash plan approve <id>` (exit 5: add `--skip-review`, as the user approved), then in the shell, not the Skill tool, run `kengash skills show ticket` and follow it from step 1 for plan `<id>`;
   - reject: `kengash plan reject <id> --why "<the user's reason>"`.

Done when `kengash plan show <id>` prints `status: ticketed` or `status: rejected`.
