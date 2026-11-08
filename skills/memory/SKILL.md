---
name: memory
description: Use when the user states a lasting preference, working style or goal, turns an approach down for good, or a design decision is made that later sessions must respect, such as "from now on", "always", "never", "remember that" or "we decided".
metadata: {source: kengash-ai}
---
# Remember it through kengash

Memory lives in the kengash store, shared by every agent and session. Record it only with `kengash memory add`, run as its own shell call with nothing chained; never edit memory files, AGENTS.md or other instruction files yourself.

0. Run `kengash --version`. If it does not print `kengash-ai <version>`, say "Install Kengash AI first: uv tool install kengash-ai" and stop.
1. Record only what is settled and binds later work; never one ticket's details, what the code, README or plan already says, a guess, or a secret. Write it as one line of about 20 words, in the user's terms.
2. A preference, working style, goal or turned-down approach:

   ```
   kengash memory add "<fact>" --why "<why it matters>" --section "<Working style|Goals|Preferences|Turned down>"
   ```

3. A design decision (architecture, module boundaries, interfaces, data formats, a library or tool, design-system values such as palette, type or motion timings, platform or performance targets, a source of truth, naming), run from inside the project:

   ```
   kengash memory add "<decision>" --why "<reason>" --decision --rejected "<alternative>"
   ```

   Leave out `--rejected` when nothing was turned down.
4. How this project builds, tests or ships, run from inside the project:

   ```
   kengash memory add "<rule>" --why "<why>" --process
   ```

5. The command prints `MEMORY.md +1 line`, `DECISIONS.md +1 line`, `PROCESS.md +1 line` or `already recorded`.
6. Tell the user in one line what you recorded.
