---
name: grill
description: Use when the user runs /kengash:grill with a feature, change or project to plan after being questioned about it.
disable-model-invocation: true
metadata: {source: kengash-ai}
---
# Grill, then plan

You question the user until nothing is left to assume, then write the plan. Read with your file tools; use the shell only for the `kengash` commands below, one per call. Never edit the repo's files or the `.kengash` store yourself.

`<scope>` below is `-p <project>` when the request names its project or folder (a path kept as typed), else empty. On exit 4 `not a kengash project`, ask whether to register that folder; only on yes, run `kengash init <folder>`, then retry.

0. Run `kengash --version`. If it does not print `kengash-ai <version>`, say "Install Kengash AI first: uv tool install kengash-ai" and stop.
1. Run `kengash context <scope>`, and `kengash settings get grill.round_size <scope>`.
2. Start the plan with the user's request verbatim:

   ```
   kengash plan new --mode grill --title "<short title>" <scope> <<'EOF'
   <the user's request, verbatim>
   EOF
   ```

   It prints `plan <id> grilling`; keep the id.
3. Look facts up. Ask only what the user alone decides.
4. Ask a round of at most `grill.round_size` questions, each with your recommended answer; use your multiple-choice tool if any. Wait; repeat until nothing is left.
5. Restate the shared understanding; wait for confirmation.
6. Save the plan: one Decisions line `question → answer` per answer; one Lasting decisions line `- <decision>. why: <reason>.` per choice later work follows, or `none`:

   ```
   kengash plan save <id> <<'EOF'
   ## Goal
   ## Decisions
   ## Lasting decisions
   ## Assumptions
   ## Scope
   ## Out of scope
   ## Design
   ## Acceptance
   - [ ] <checkable criterion>
   ## Test seams
   ## Risks
   EOF
   ```

7. Run `kengash plan review <id>` with a 10-minute shell timeout; on exit 3, run it again. Show the verdict and every finding. Under `loop_start: auto` a pass needs no question: approve. Else ask: approve, edit or reject?
8. Act on the answer: edit → change, save, review again; approve → `kengash plan approve <id>` (exit 5: add `--skip-review`, as the user approved), then in the shell, not the Skill tool, run `kengash skills show ticket` and follow it from step 1 for plan `<id>`; reject → `kengash plan reject <id> --why "<the user's reason>"`.

Done when `kengash plan show <id>` prints `status: ticketed` or `status: rejected`.
