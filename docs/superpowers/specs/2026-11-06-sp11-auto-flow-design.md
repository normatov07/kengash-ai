# SP11: Auto flow, plan to tickets to loop (design)

Date: 2026-11-06. Status: written from the user's request of 2026-11-06 and two choices they made the same day (tickets go in at once after a plan is approved; the Auto mode switch sits in Settings and on Overview); calls marked *call* are the builder's and open to veto.

## 1. Why

The user, on 2026-11-06: "when I use plan command it stops after planning however it should continue make ticket based on these plan. we need to automate it, minimise user interaction after planning." After the user approves a plan, the session should cut it into detailed tickets at once. Once the tickets are in, it should either ask whether to run the loop, or, when the user has turned Auto mode on in the UI, start the loop without asking. "But first we need to check the loop command is currently running or not; if it is running already in another session we should not run it again."

Today (0.3.0):

1. `/kengash:plan` and `/kengash:grill` end at `status: approved`. `/kengash:ticket` waits for a yes on its slice list, then tells the user to type `/kengash:loop`. That's three commands and two confirmations after the one decision that matters.
2. Skills cannot call each other. User skills set `disable-model-invocation: true`, and Codex installs them as `kengash-<name>` copies, so one skill cannot name another's file by a path that works for every agent.
3. Nothing stops two loops. `next` and `wait` only record conductor pings for the UI. Two conductors that both cover a project both answer its gates. Two conductors on the same scope also share one wait cursor, so each one silently loses the events the other read.
4. A running loop only sees new tickets when it goes idle. `wait` does not report a ticket that becomes ready, whether it was just added or just unblocked by a merge, so those tickets sit idle while other work runs.

## 2. Goals, non-goals, anti-goals

- Goal: after the user approves a plan, the same session adds its tickets with no further question.
- Goal: once tickets are added, the session checks for a running loop that covers the project. If one runs, it says so and stops, because that loop picks the tickets up. If none runs, it starts the loop itself when Auto mode is on, and asks once when it is off.
- Goal: at most one live loop covers any project, enforced by `kengash`, not by the skills' good behaviour.
- Goal: a running loop starts newly ready tickets as soon as they appear.
- Goal: Auto mode is one setting, switched in the UI (Settings and Overview) and readable from the CLI.
- Non-goals: the UI starting a loop or an agent session. There is no daemon (hard rule 7); a loop is a conductor session in the user's agent. Approving plans automatically. Merging automatically (`merge.mode` already does that). Locking across machines (the store is local).
- Anti-goals: two conductors waiting on overlapping scopes; a lock that outlives its session and blocks every later loop; tickets added while a loop winds down and then left unrun; a loop started while Auto mode is off without the user's yes; a skill or the UI writing store files outside `kengash` (hard rule 4).

## 3. Decisions: the hand-off (milestone 2)

1. **`kengash skills show <name>`** prints a packaged skill the way `skills install` would have rendered it for the agent that asks. An unknown name exits 1 with the known names. This is how one skill hands over to the next (*call*: a relative path would differ between the Claude plugin folder and Codex's `kengash-<name>` copies, and model invocation is Claude-only). The output:
   - Starts with the body, without the frontmatter.
   - Names the command `kengash` when this CLI is the first `kengash` on PATH, and otherwise by this CLI's full path. That is the same rule `--cli-name` follows (`ops/skills.py` `rename_cli`), so a user who installed with a full path gets the same commands back.
   - Spells the other skills as the calling agent types them: `/kengash:<name>` for claude and agy, `$kengash-<name>` for codex. The agent is `$KENGASH_AGENT`, else the detected conductor (§4.1), else claude.
   - Ends with each file under the skill's `references/`, as its own `## references/<file>` section. This keeps "read `references/importance.md` when …" true, because the rubric is in the same printout (*call*: an absolute path into site-packages may sit outside a sandboxed agent's reach).
2. **Plan and grill continue into tickets.** On the user's approve, the skill runs `kengash plan approve <id>` (with `--skip-review` only as today), then `kengash skills show ticket`, and follows it from step 1 for plan `<id>`. Edit and reject are unchanged. These skills are done when the plan is `ticketed` or `rejected`.
3. **Tickets go in at once from an approved plan** (the user's choice). The numbered slice list is still shown, for information, and `kengash ticket add` follows without waiting. A quick plan made from a short prompt still waits for the user's yes on the list, because that check is a quick plan's only approval (system spec §6).
4. **Detailed tickets.** Each slice's `scope` runs 3 to 8 lines: what the slice delivers end to end, the files or modules and interfaces it changes, the plan sections it implements (by heading), and what it leaves to other slices. `acceptance` holds checkable criteria drawn from the plan's Acceptance. Tickets still reference the plan by id and never copy the prompt (hard rule 5).
5. **After the tickets.** The ticket skill runs `kengash loop status -p <project>`, with the project from the plan's `project:`. What happens next:
   - `loop running: …`: the skill tells the user that loop will pick the new tickets up, and stops. If nothing starts, the user runs `/kengash:loop` and says to take over.
   - `no loop running` and `loop_start: auto`: the skill runs `kengash skills show loop` and follows it with `<project>`.
   - `no loop running` and `loop_start: ask`: the skill asks once, "Run the loop now?". On yes it follows the loop skill; on no it gives the ticket ids and says `/kengash:loop` runs them.
6. **The started loop covers the plan's project only** (*call*: the session planned that project; other projects keep their own loops or wait for `/kengash:loop`).
7. **The loop skill claims first.** After `doctor` it runs `kengash loop claim [-p <project>]`. On exit 6 it tells the user which session runs the covering loop and stops. It reruns with `--take-over` only when the user says so.
   - When `kengash wait` exits 6, another conductor has taken over, and the loop stops the same way.
   - A new `queued` row in the event table runs `kengash next` and starts what it lists. `queued` lines are handled before any line that needs the user, so new work starts before the loop waits on a question.
   - When the loop ends (nothing runnable and nothing running), it runs `kengash loop release`. On exit 1, `not released`, it goes back to `kengash wait` (final review: back to `next` would spin while tickets wait for a slot).
   - When `kengash run` starts none of the listed tickets, it shows the `skipped <id>: <reason>` lines and asks the user how to go on, instead of cycling (final review).
   - When the user says to stop, it runs `kengash loop release --force`.
8. **Skill caps hold.** The lint counts the whole file, frontmatter included (`ops/skills.py` `_lint_one`). By that count plan, grill, loop and ticket are at 399, 400, 376 and 315 of 400 words. The edits fit `skill.max_words` and `skill.max_lines` by tightening wording; the caps and the lint stay as they are (*call*). M2 reruns these skills' evals anyway, so the tightened wording is proven again. If grill still cannot fit, its round rules move to `grill/references/rounds.md`, read when asking a round.

## 4. Decisions: the loop lease (milestone 1)

1. **A lease per conductor.** `runtime/loops/<pid>.json` holds `LoopLease{pid, agent, command, project: slug | None, started, seen}` (a new model in `model.runtime`; the store reads and writes it; it is git-ignored like all of `runtime/`). The conductor is the process `waiting.ping` already finds: the nearest ancestor named `claude`, `codex` or `agy`, otherwise the parent. Checked on 2026-11-06: `kengash` run from Claude Code's Bash tool has `bash → claude` as its ancestry, and that `claude` pid stays the same for the whole session. `command` is that process's name at claim time.
2. **Live** means the pid is alive, its process name still equals `command` (which guards against a reused pid), and `seen` is under `LOOP_STALE_S = 3600` seconds old. *call*: a conductor that waits more than an hour for the user's answer can be taken over; one hour is long enough to cover a normal pause. Readers ignore leases that are not live. Only `claim` deletes them, and it journals each one as `loop.ended` with reason `gone`, as it does for an old lease on the caller's own pid that another program held. A lease file that cannot be read (damaged, or written by a newer version) is skipped: it holds no loop.
3. **Coverage.** A lease with no project covers every project; a lease with a slug covers that project. Two scopes overlap when either one is every project, or when both name the same slug.
4. **`claim(project, take_over=False)`** runs under `runtime/locks/loops.lock`:
   - It first drops leases that are not live.
   - If a live lease held by another pid overlaps the scope, it raises `LoopBusy` (exit 6) with `loop running: <agent> pid <pid> on <scope>, seen <age> ago; if that loop has ended: kengash loop claim --take-over` (the hint added after the final review, for skills that never release). With `take_over`, it removes that lease instead and journals `loop.ended`, reason `taken_over`.
   - The caller's own lease is replaced: the scope becomes the new one, and `started` is kept when the scope is unchanged.
   - It journals `loop.started` only when the lease is new or its scope changed.
5. **Heartbeat.** `waiting.ping`, which `next` and `wait` already call, refreshes `seen` on the caller's own lease. Before it waits, `wait` checks the scope:
   - When the conductor was found by process name (an ancestor named `claude`, `codex` or `agy`), `wait` claims the scope as in decision 4, without `take_over`. An old loop skill that never claims therefore still holds a lease while it waits. A conductor whose lease was taken over gets exit 6 instead of sharing the other conductor's events.
   - Any other caller, such as a terminal or the parent-pid fallback, claims nothing, so a long-lived shell never holds a lease it did not ask for. It still gets exit 6 when another live lease covers its scope (*call*).
6. **`release(project, force=False)`** runs under the same lock.
   - When the caller holds no lease, it prints `no loop held here` and exits 0.
   - Without `force`, when `next` would list runnable tickets in the lease's scope, it refuses with exit 1: `not released: N runnable; run: kengash next`.
   - Without `force`, when ready tickets in the scope (not paused) wait while a live worker of any project holds a slot, it refuses with exit 1: `not released: N ready, waiting for a slot; run: kengash wait`. Slots are machine-wide, so a project's loop must outlive another project's busy workers (final review).
   - Otherwise it deletes the lease and journals `loop.ended`, reason `released`. `force` is for a stop the user asked for.

   Why this closes the hand-off race: session B always adds its tickets before it claims, and claim and release are ordered by the lock. So either loop A's release sees B's ready tickets and keeps looping, or A has already gone and B's claim succeeds.

   A loop the user interrupts without a release keeps its lease until its session exits, or for up to `LOOP_STALE_S`. Meanwhile other sessions are told which session holds it, and `--take-over` frees it on the user's word.
7. **`status(project)`** is read-only. It returns the live leases that overlap the scope (all of them when no project is given) and the scope's resolved `loop_start`.
   - Another conductor's lease prints as `loop running: …`.
   - The caller's own lease prints as `this session holds the loop on <scope>`. That is never `loop running:`: one session cannot plan while it loops, so its own lease means a loop that has stopped, and the ticket skill goes on to claim, which refreshes the lease.
8. **CLI** (each command takes `--json`; `claim` and `status` take `-p/--project`, while `release` acts on the caller's own lease and takes none, *call*):
   - `kengash loop claim [--take-over]` prints `loop claimed: <scope>`.
   - `kengash loop release [--force]` prints `loop released: <scope>`, `no loop held here`, or `not released: …`.
   - `kengash loop status` prints one line per live lease, `loop running: <agent> pid <pid> on <scope>, seen <age> ago`, or `no loop running`, and then `loop_start: ask|auto`.

   `<scope>` is the slug or `all projects`. The new `ops.loops` holds the use cases, and the conductor lookup moves there from `waiting`, which keeps `ping` and `wait`.
9. **`wait` reports `queued`.** A `ticket.created` event whose status is `in_queue/ready`, or a `ticket.moved` event to `in_queue/ready` (which a merge emits for each ticket it unblocks), or a `ticket.recirculated` event whose status is `in_queue/ready` (a merge conflict sends the ticket back to the queue), comes back as `<id> queued loop n/max: <title>` in `--json`; the text output folds every queued event into one line, `queued: N tickets ready; run: kengash next`, after the other lines, and points capped lines at `kengash status` (which lists open gates), never at a second `wait` whose cursor has moved on (final review). While ready tickets in scope wait on a slot a live worker holds, `wait` is not `idle`; it returns `idle` once a held slot frees, so the loop runs `next` again. A `wait` already polling checks each round that its conductor still holds the lease and raises LoopBusy once another conductor took over, before it reads further (final review). The journal and the wait cursor keep these events while the conductor talks to the user, so a loop that is waiting on a question starts the new tickets as soon as it next runs `wait`. B's message to the user says so.
10. **Exit code 6**, "another loop covers this scope", joins the system spec's list. `model.errors.LoopBusy` carries it.

## 5. Decisions: Auto mode (milestone 3)

1. **Setting.** `loop_start: ask | auto`, default `ask`. It is validated, resolved like every other key (package, then defaults, then project), seeded with a comment in the package's SETTINGS.md, and added to system spec §4.6. `kengash settings get loop_start` reads it.
2. **Settings screen.** In *Planning and merging*, a switch reads "Auto mode", with the hint "Start the loop as soon as tickets are added". It writes `loop_start: auto` when on and `ask` when off. It saves with the screen's Save, and shows the amber "set here" mark when the scope overrides the value.
3. **Overview.**
   - The subtitle shows the loops that cover the selected project (or every loop under all projects): `loop running (claude · all projects)`, `2 loops running (claude, codex)`, or `no loop running: run /kengash:loop in your agent`. This replaces the conductor count (*call*: the lease says whether work is being conducted; pings stay in the data).
   - A compact Auto mode switch in the header acts on the selected scope: the selected project, or the defaults under "All projects". It saves at once through `POST /api/settings`, like the pause control, and a failed save puts the switch back with the error. On a project, a value equal to the defaults' removes the project's own key, so the project keeps following the defaults. Under "All projects", the hint reads "every project without its own setting" (*call*).
   - `views.Overview` gains the live leases and the resolved `loop_start` for the defaults and for each project.
4. **Live refresh.** The `loop.started` and `loop.ended` events reach the UI through the existing journal SSE. A loop that dies or goes stale writes no event, so Overview also reloads every 30 seconds while it is shown and holds no unsaved edit (*call*). Leases are filtered for liveness on each read.
5. **Canvas.** Overview's switch and loop line are an addition the user chose on 2026-11-06. The rest of Overview keeps canvas parity, and AGENTS.md's "UI design source" names this section.

## 6. Contract changes (system spec, same commit as the code)

- §4.1 runtime layout: `loops/<pid>.json`, `locks/loops.lock`.
- §4.6: `loop_start`.
- §6: exit code 6; table rows `kengash loop claim|release|status`, `kengash skills show`; `wait` lists `queued`; a paragraph on leases (decisions 4.1 to 4.6).
- §6.1 event types: `loop.started`, `loop.ended` (reason `released`, `taken_over`, `gone`).
- §8.1: plan and grill end in `ticket`; `ticket` adds tickets at once from an approved plan and ends with the loop check; `loop` claims, handles `queued`, and releases.
- `docs/conventions/skills.md`: a skill hands over through `kengash skills show <name>`, never a path.

## 7. Milestones and exit criteria

| M | Scope | Exit |
|---|---|---|
| M1 | Lease model, store and `ops.loops`; `kengash loop claim\|release\|status`; `wait` claims, refuses and reports `queued`; exit 6; `kengash skills show`; `loop_start`; journal events | unit and CLI tests for every row of §8; `make check` green |
| M2 | Plan, grill, ticket and loop skills; evals | `kengash skills lint` clean within caps; evals green on claude (and agy) for: plan → approve → tickets → "not now"; ticket from an approved plan with no yes turn; `loop_start: auto` starting the loop; a second `/kengash:loop` refused while a lease is held |
| M3 | Settings switch, Overview line and switch, docs | UI tests for the save and the view; screens checked at 360 px and desktop; docs and CHANGELOG updated |

Each milestone ends with a critical review against this spec (hard rule 9).

## 8. Test seams

- The conductor identity and the pid checks are injected or monkeypatched. A live lease uses the test's own pid and process name. A dead lease uses the pid of a subprocess that has exited. Staleness comes from `seen` written in the past.
- Claim: a free scope; the caller's own lease (refreshed, or rescoped); another pid's live lease on the same project, on every project, and on a different project (allowed); a stale lease and a dead pid (claimed, journaled `gone`); `--take-over`.
- Release: no lease; runnable tickets left (refused); `--force` with runnable tickets; clean.
- Status: another conductor's lease (`loop running:`) against the caller's own lease (`this session holds the loop`).
- `wait` from a caller with no detected agent: no lease written; exit 6 under another conductor's live lease.
- `skills show`: the command name as `kengash` against a full path; `$kengash-` spelling under codex; references inlined.
- Race: B adds tickets, A releases (refused), B's claim is busy, A runs `next`. In the other order: A releases, then B claims successfully.
- `wait`: claims for an old skill; exits 6 after a take-over; reports `queued` for a ready add and for an unblock, but not for a blocked add.
- Skills: `skills show` prints every packaged skill without frontmatter; lint passes.
- UI: the settings save of `loop_start`; the overview fields; the switch reverts on a failed save.

## 9. Risks

- **Conductor identity.** An agent whose process is not named `claude`, `codex` or `agy` falls back to the parent pid, which is a fresh shell for each tool call, so its own `wait` would look like another conductor. Mitigations:
  - `$KENGASH_AGENT` keeps naming the agent, as today.
  - The fallback lease belongs to a short-lived shell, so it is never live after that shell exits. Claims by such a conductor never block anyone for long.
  - The live smoke checks that the lease pid stays stable across two `kengash` calls on claude and agy.
  - Codex's process tree cannot be checked until the user installs codex. Until then, the one-loop guarantee for Codex is unverified.
- **Held-back tickets at a release.** Tickets that wait for a slot keep the loop alive (decision 4.6). Tickets held back for other reasons (a signed-out provider, a paused project) do not: A ends, and B, told a loop was running, ends too, so they wait for the next `/kengash:loop`. B's message says to run `/kengash:loop` if nothing starts. *call*: accepted, because refusing release on those would keep a loop that cannot progress.
- **Word caps.** The skill edits are tight against 400 words. If they cannot fit, the event table moves to `loop/references/events.md`, read when acting on an event.
