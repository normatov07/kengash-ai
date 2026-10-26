---
name: to-plan-with-grill
description: Use when the user runs /to-plan-with-grill with a feature, change or project to plan after being questioned about it.
disable-model-invocation: true
metadata: {source: kengash-ai}
---
# Grill, then plan

You question the user until nothing is left to assume, then write the plan; harness stores it and has another agent review it. Read with your file tools; use the shell only for the `harness` commands below, each as its own call with nothing chained before or after it. Never edit the repo's files or the `.harness` store yourself.

0. Run `harness --version`. If it does not print `kengash-ai <version>`, say "Install Kengash AI first: uv tool install git+https://github.com/normatov07/kengash-ai" and stop.
1. Run `harness context`, and `harness settings get grill.round_size` (questions per round).
2. Start the plan with the user's request, word for word:

   ```
   harness plan new --mode grill --title "<short title>" <<'EOF'
   <the user's request, verbatim>
   EOF
   ```

   It prints `plan <id> grilling`; keep the id.
3. Look facts up yourself (code, docs, memory; a subagent if you have one). Ask only what the user alone can decide.
4. Ask a round of at most `grill.round_size` questions, each with your recommended answer; use your multiple-choice tool if you have one. Wait for the answers. Repeat until nothing is left to ask.
5. Restate the shared understanding in a few lines and wait for the user to confirm it.
6. Save the plan; Decisions holds one `question → answer` line per answer:

   ```
   harness plan save <id> <<'EOF'
   ## Goal
   ## Decisions
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

7. Run `harness plan review <id>` with a 10-minute shell timeout; on exit 3, run it again. Show the user the verdict and every finding; ask: approve, edit or reject?
8. Act on the answer: edit → change, save, review again; approve → `harness plan approve <id>` (add `--skip-review` only when it exits 5 and the user said to approve); reject → `harness plan reject <id> --why "<the user's reason>"`.

Done when `harness plan show <id>` prints `status: approved` or `status: rejected`.
