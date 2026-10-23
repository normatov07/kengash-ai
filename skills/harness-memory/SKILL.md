---
name: harness-memory
description: Use when the user states a lasting preference, working style or goal, turns an approach down for good, or a design decision is made that later sessions must respect, such as "from now on", "always", "never", "remember that" or "we decided".
metadata: {source: super-harness}
---
# Remember it through harness

Memory lives in the harness store, shared by every agent and session. Record it only with `harness memory add`, run as its own shell call with nothing chained; never edit memory files, AGENTS.md or other instruction files yourself.

0. Run `harness --version`. If it does not print `super-harness <version>`, say "Install super-harness first: uv tool install git+https://github.com/normatov07/super-harness" and stop.
1. Write the fact as one line of about 20 words, in the user's terms.
2. A preference, working style, goal or turned-down approach:

   ```
   harness memory add "<fact>" --why "<why it matters>" --section "<Working style|Goals|Preferences|Turned down>"
   ```

3. A design decision, run from inside the project:

   ```
   harness memory add "<decision>" --why "<reason>" --decision --rejected "<alternative>"
   ```

   Leave out `--rejected` when nothing was turned down.
4. The command prints `MEMORY.md +1 line`, `DECISIONS.md +1 line` or `already recorded`.
5. Tell the user in one line what you recorded.
