# SP15: Feedback loop — checks inside the editing step, failures agents can act on (design)

Date: 2026-11-07. Status: from the user's report on chess-samurai ("tickets fail test or review again and again… agents must know why it fails") and the investigation below; the user chose kengash running the checks itself inside the editing step. Calls marked *call* are the builder's.

## 1. Why

The chess-samurai store (9 tickets run, 2026-11-06/07) shows `run_tests` failing 22 times (14 tests, 8 lint) against 3 `review_code` failures; 8 of 9 tickets failed their first `run_tests`. Every failure costs a whole loop: an implementer call of 2–8 minutes, then the checks again. Ticket d24db74a reached its loop cap with 3 of 5 loops spent on test and lint failures. Causes, worst first:

1. **The agy implementer cannot run anything.** `adapters/antigravity.py` `EDIT_LINE` tells it "Terminal commands are not available… do not run tests; review steps check the result." Across 6 implement calls on d24db74a it made 0 `run_command` calls and read `.git/logs/HEAD` as a file. A claude implementer is allowed `Bash(<test_cmd>)` and `Bash(<lint_cmd>)`; agy gets neither.
2. **The failure text drops the error.** `adapters/shell.py` puts the last 20 lines of output in the finding. `flutter test` prints a failure where it happens and ends with progress lines: d24db74a's loop-1 finding was 20 passing test names and "Some tests failed."; the failing test and its Expected/Actual colours were cut. For `flutter analyze`, about 12 of the 20 lines were `pub get` noise. The finding's `fix` reads "make project.test_cmd pass" and never names the command, against SP12 spec §5.5 ("quotes the failing command").
3. **No prompt names the checks.** `test_cmd` and `lint_cmd` reach no prompt text, although SP12 §5.5 says reviewers see both. The implementer did not know `flutter analyze` fails on `info` issues and traded `prefer_const_constructors` for `unnecessary_const`, one loop each.
4. **A resumed implementer is not told why it is back.** It gets `Loop 3, step implement: Implement the ticket in this worktree, with tests.` and the Findings; nothing says `run_tests` sent it back or what failed.
5. **Unverified claims.** With no terminal, the implementer's handoff said "Ran test suite… all 57 tests passing".
6. **Scope the implementer cannot do.** d24db74a asks for a download from a claude.ai artifact (needs a login) and font subsetting (`pyftsubset`); the planner does not know what the implementer can run.

The code reviewer works: it read the diff and its findings were real and specific.

## 2. Goals and non-goals

- Goal: a check failure reaches the implementer, in the same conversation and within the same loop, as the failing command, its exit code and the lines that say what broke; a loop is spent only when the implementer cannot fix it in its fix turns.
- Goal: every agent that edits or reviews knows the project's checks; a resumed agent knows which step sent it back and why.
- Goal: less wall time per ticket: fewer loops, and `run_tests` does not rerun checks on a commit that already passed them.
- Non-goals: parsing each test framework's output into one finding per test (the excerpt is framework-agnostic); a new gate when the implementer says it is blocked (§5); changing the reviewer.
- Anti-goal: a step that can now fail where it passed before. Fix turns only add chances; when they run out, the step passes as today and `run_tests` routes the ticket back as today.

## 3. Decisions

1. **Checks inside an editing step** (the user's choice).
   - After an `edit`-kind step's CLI call succeeds, kengash runs the project's checks in the worktree with the shell adapter (`test_cmd`, then `lint_cmd`, as `run_tests` does), before it commits.
   - They run only when `checks.turns > 0`, at least one command is set, and the ticket's workflow has a `check`-kind step after this step (*call*: a user who left `run_tests` out of a workflow chose not to test it).
   - On failure, and while fix turns remain, kengash resumes the step's session with the fix prompt (§3.4) and runs the checks again after its reply. Each fix turn is a resumed turn like the commit-hook repair turn: a `network` error gets one resumed turn, any other error fails the ticket through the existing `_call_failed` path. Usage adds to the step's tokens; the last reply's Handoff is the one kept.
   - When the checks pass, or the turns run out, the step continues as today: commit, Handoff, Log, route. Running out never fails the step.
   - Setting `checks.turns: 2` (0 = off), in §4.6 under `# loops` with the comment `fix turns an editing step gets when kengash's checks fail after it (SP15)`.
   - Every check run journals `checks.end` with `step`, `turn` (0 for the first run), `verdict`, `summary`, `duration_s` and `log`, and appends a ticket Log line `- <time> · checks · kengash · shell/default · <verdict> · 0 · <summary>` (*call*: the existing Log format, so the UI and `kengash logs` show it with no new parser).
   - Each check run takes its own log number (`<id>-<n>.out`), as `run_tests` does.
2. **A failure digest instead of the tail.** A new pure function `adapters.digest.excerpt(output, *, log)` returns `(headline, text)`:
   - strips ANSI escapes; finds marker lines: case-insensitive `error|fail(ed|ure)?|exception|traceback|assert|expected|actual|panic|not found|undefined|cannot|can't`, the tokens `[E]`, `✗`, `✘`, `FAILED`, `ERROR`, analyzer rows `^\s*(info|warning|error) •`, and `<path>.<ext>:<line>` references;
   - keeps each marker with 2 lines before and 8 after, merges overlaps, keeps order, and always adds the last 2 non-empty lines (the runner's summary);
   - caps at 60 lines and 4,000 characters, each line at 300, keeping the earliest blocks (the first error is usually the cause) and ending with `… <n> more lines; full output: <log>`;
   - with no marker, keeps the last 30 lines;
   - `headline`: `` `<command>` exit <code>: <first marker line, trimmed to 160> ``.
   The marker list and window sizes are *call* within these bounds; tests pin them on real fixtures.
3. **A check failure's ticket record.**
   - Finding: one line per failing check, `- high · <file>:<line> · <headline> · fix the cause in Check output, then run <command>`. `file:line` is the first `<path>:<line>` reference in the digest that names a file inside the worktree, relative to it; otherwise `-:0`. One line keeps the `## Findings` format and makes the stall fingerprint stable when the same check fails the same way.
   - New ticket section `## Check output`, after `## Findings`: the digest in a fenced block, prefixed by the headline. kengash writes it on a failing `run_tests` and on a failing in-step check run, and clears it when the checks pass. At most 62 lines (headline, fence, 60).
4. **Prompts.**
   - `## Checks` block, in new and resumed prompts of edit, review, plan and check-kind steps whenever a command is set: ``kengash runs these in the worktree after editing steps; each must exit 0:`` then `- tests: `<test_cmd>`` and `- lint: `<lint_cmd>``. Reviewers get it as context (SP12 §5.5).
   - Edit steps (new and resumed) also get `## Check output` when the section is set.
   - **Sent back.** When a failing verdict routes a ticket back, kengash stores `TicketState.sent_back = {step, summary}` (the failing step and its output's `summary`). The next prompt of the target step says so: resumed, `Loop <n>, step <step>: <failing step> sent this back: <summary>. Fix every Finding below, then run the failing check.` in place of the step instruction; new, the same sentence after the step instruction. Cleared when that step passes.
   - **Fix prompt** (a fix turn): ``kengash ran the checks after your reply (fix turn <t> of <n>): <headline>`` + `## Check output` + `Fix the cause, then run <command> if your tools allow. Reply again with JSON that matches the schema.``
5. **agy may run the checks.** For `edit_worktree`, `--settings` allows `read_file(*)` plus `command(<cmd>)` for `test_cmd` and `lint_cmd` and `command(git status)`, `command(git diff)`, `command(git log)`, `command(git show)`. A command holding a shell operator (`&&`, `||`, `;`, `|`, `>`, `<`, `` ` ``, `$(`) is not allowed, since agy checks each part of a line. `EDIT_LINE` becomes: `You may run only these terminal commands, each on its own with no &&, ;, pipes or redirects: <list>. Any other command ends your turn; read and edit files with your file tools.` With nothing allowable it keeps today's line. The existing denied-action repair turn stays the remedy for a stray command. A live probe at build time confirms `command(flutter test)` allows `flutter test test/x_test.dart` and that `ls` is still denied.
6. **`run_tests` reuses a passing in-step result.** After the commit of a step whose last in-step check run passed, with no commit-hook repair turn after it, kengash stores `TicketState.checked = {commit, summary}`. A shell `run_tests` step whose worktree HEAD equals that commit and whose worktree is clean returns `pass` with `<summary> (in <step>, same commit)` without running anything, and journals `step.end` as usual with `duration_s: 0`. Any other case runs the checks. A failing in-step result is never reused (*call*: a flaky failure gets its rerun).
7. **Role skills.**
   - `implement`: run the commands in the prompt's Checks block before replying when your tools allow; never report a check you did not run, write `checks not run` instead; when sent back, fix the cause Check output names, first error first; when part of the Scope cannot be done here (a login, a download, a tool you cannot run), do the rest and start the handoff with `BLOCKED: <what and why>`.
   - `plan`: the implementer edits files and runs only the Checks commands; a Scope item that needs a login, a download or another tool goes under `Risks:` as `BLOCKED: <what>` so the user can supply it.
   - Both stay within `skill.max_lines` and `skill.max_words`; RED/GREEN wording follows `docs/conventions/skills.md`.

8. **Mechanics** (all *call*).
   - The shell adapter puts the digest in a new `StepResult.check_output: str` (headline line, then the digest); `ops` writes it to `## Check output`. `adapters.digest` imports only `model`, like every adapter.
   - `TICKET_SECTIONS` gains `"Check output"` between `Findings` and `Log`.
   - During an in-step check run the step keeps its provider slot (the fix turn needs the session), the ticket keeps the edit step's status, and `TicketState.running` names `test-runner`/`shell` with the check's log, so `kengash ps`, `logs -f` and the Live tab show the check.
   - A check run that times out ends the in-step checks with no fix turn; the step continues and `run_tests` judges.
   - "A `check`-kind step after this step" means one that is on (its role switched on) in the ticket's resolved workflow.
   - The UI Timeline shows `checks.end` as a row like `step.end` (`checks · fail · lint failed (exit 1) · turn 1`); the agent chain's per-step counts stay `step.end` only.
   - The reuse record is `TicketState.checked = {commit, summary}`.

## 4. Contract changes (system spec and SP3 spec §8.2, same commits as the code)

- System §4.4: `## Check output` in the ticket template; system §4.6: `checks.turns`; §6.1: `checks.end`; §7.1: the in-step checks between items 5 and 6, and `run_tests` reuse.
- SP3 §8.2: the `## Checks` block, the sent-back head, the fix prompt.
- `docs/conventions/memory-files.md`: the `## Check output` row (kengash, 62 lines).
- Module READMEs: `adapters`, `ops`, `roles`, `model` (hard rule 2).

## 5. Left out, on purpose

- A `BLOCKED:` handoff opening no gate yet: the reviewer still decides. If loops keep burning on blocked scope, a later change can send such a ticket to `needs_approval`.
- Per-framework parsers (flutter `--reporter`, pytest `-rf`): the digest is generic; a project can still set a quieter `test_cmd`.

## 6. Milestones and exit criteria

| M | Scope | Exit |
|---|---|---|
| M1 | §3.2–3.3: digest, finding, `## Check output`; §3.4 prompts and sent-back; skills §3.7 | digest tests on fixtures trimmed from the chess-samurai logs (flutter test assertion, flutter compile error, flutter analyze infos) plus pytest and a marker-less failure; finding and section writes and clears; prompt tests; skill lint |
| M2 | §3.1 in-step checks, §3.6 reuse, §3.5 agy allow-rules; contract docs | step tests: pass first run, fail then fixed, turns exhausted (step passes, `run_tests` fails, loop + 1), no check step in workflow, `checks.turns: 0`, network error in a fix turn; reuse on same commit, rerun on another or dirty worktree; agy argv with simple and operator commands; `make check` green; live probe of the agy rule |
| M3 | Critical review against §1–§3; replay | a chess-samurai ticket rerun on the new build: failing checks fixed inside the implement step, Findings name the failing test or lint row |
