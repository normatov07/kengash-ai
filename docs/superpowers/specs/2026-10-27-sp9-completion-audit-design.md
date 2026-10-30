# SP9: Completion audit (design)

Date: 2026-10-27. Status: written under the user's instruction to analyse the code, plans, requirements and specs, test that everything works, and finish what is still missing with best practices; calls marked *call* are open to veto.

## 1. Why

Audit on 2026-10-27, against `full prompt of app.md`, the system spec and SP2–SP8: `make check` green (637 passed); the seven screens render a demo store in headless Chrome with no console or CSP problem; every SP acceptance box is ticked except Codex, which is not installed. Read against the original request and run for real, five things are still open:

1. **Project argument (request step 7).** `/to-loop [project name or folder]` and `/to-ticket <prompt> [path to project]` take an optional project. The skills ignore it, and `--project` accepts only a registered slug, never a folder.
2. **Tags on the board (request step 6).** The board should show "status, tags, importance, loop circle count". Cards show all but tags; tags appear only in the ticket sheet and the filter.
3. **Names left over from SP8.** `make lint` and `make evals` call `harness`, so every `make check` prints the deprecation line and both targets break in 0.3.0; `scripts/demo_store.py` builds a `.harness` home and prints `HARNESS_HOME=… harness ui open`. `make live` (claude 2.1.311, agy 1.4.8): 8 passed, 4 codex skips, and both end-to-end smokes ran plan → implement → review → merge with working code, then failed on the last check, which still greps `Harness-Ticket` although new commits carry `Kengash-Ticket`.
4. **A race in `kengash wait` (found while testing).** `tests/test_lifecycle.py` failed about once in ten runs, on `main` too: `wait` read the journal, then judged "nothing runs" from ticket files. A worker saves its ticket at a gate before it journals the gate, so between the two `wait` answered `idle` and dropped the gate; `/to-loop` would then end the loop without asking for the merge.
5. **Codex.** Live smoke, evals and a Codex plugin manifest wait for the codex CLI to be installed and signed in, which only the user can do.

## 2. Goals, non-goals, anti-goals

- Goals: every command that takes `--project` accepts a project name or a folder; the planning and loop skills pass the user's optional project on; board cards show tags; our own tooling uses only kengash names.
- Non-goals: registering a folder without asking; Codex work beyond saying what the user runs.
- Anti-goals: a raw path reaching pause flags, conductor pings, settings scopes or the journal; a card row that breaks canvas parity on tickets without tags.

## 3. Decisions

1. **`--project` takes a name or a folder.** A registered slug wins. Otherwise the value is a folder (relative to the current folder, `~` expanded) and resolves to the registered project whose repo contains it; with nested registered repos the deepest one wins (*call*). An existing folder no project contains exits 4, `not a kengash project: <folder>; run: kengash init <folder>`; anything else exits 1, `unknown project: <value>`. One option callback resolves it before any use case runs, so `ops`, flags, pings and the journal only ever see slugs. The lookup is `ops.workspace.project_slug`, so `cli` keeps off the store.
2. **Skills pass the project on.** `/to-loop [project]` adds `-p <project>` to `next`, `wait` and `status`; without it the loop covers every project, as now. `/to-ticket <prompt or plan id> [project]` adds it to the quick `plan new`; plan ids are already found in every project. `/to-plan` and `/to-plan-with-grill` take the same optional trailing project for `context` and `plan new` (*call*: one rule for every planning skill). On exit 4 `not a kengash project`, the skill asks the user whether to register that folder and runs `kengash init <folder>` only on yes, because registering is the user's trust of a repo (system spec §4.2).
3. **Tags on cards.** A card with tags shows up to three as `#tag` chips after its status chips, then `+N`; a card without tags adds nothing, so the canvas boards, which have none, still match (*call*).
4. **Kengash names in tooling.** `make lint` runs `uv run kengash skills lint`, `make evals` `uv run kengash skills eval --all`; the demo store lives in `<dir>/.kengash` under `KENGASH_HOME` and its help names `kengash ui open`; the live smoke greps `Kengash-Ticket`.
5. **`wait` checks running work first.** It decides whether anything in scope runs before it reads the journal, and a live worker in scope counts as running. A worker journals its last event before it exits, so once nothing runs every event that ended the work is readable, and `idle` can no longer hide a gate.
6. **Codex stays documented as pending.** The report tells the user the install and sign-in commands; `make live` and `make evals` already pick codex up once it is signed in.

## 4. Acceptance (SP9 exit)

- [x] `-p <slug>`, `-p <repo folder>`, `-p <subfolder>` and `-p .` inside a repo give the same `next`; an unregistered folder exits 4 with the init line; an unknown name exits 1 (`tests/test_ops_workspace.py`, `tests/test_cli_queue.py`; by hand on the demo store, 2026-10-27).
- [x] `pause -p <folder>` pauses the slug, not the path (`tests/test_cli_controls.py`).
- [x] `kengash skills lint` is clean; the four skills name the optional project and the exit-4 question. Wording micro-tested on claude haiku, one fresh sample per call with the skill as system prompt: before, 0 of 21 samples scoped their commands to a named project; after, 45 of 45 scoped a named project or folder and left a bare command unscoped (a `-p` sentence apart from the commands scoped `plan new` only 2 of 3 times, so the planning skills carry a `<scope>` slot in each command). The four skills' eval scenarios pass on claude and agy (8 of 8, 2026-10-27).
- [x] A card with tags shows them and one without has no tag chips (headless Chrome on the demo store, 2026-10-27: `#webhooks`; `#ui #sse #realtime +1`).
- [x] `make check` prints no deprecation line; the demo script prints kengash names; the live end-to-end smoke passes on claude and agy (claude 2.1.311 haiku, agy 1.4.8 gemini-3.8-flash-low, 2026-10-27).
- [x] `wait` reports a gate a worker journals right after `wait` read the journal (`test_wait_is_never_idle_over_a_gate_its_worker_is_journaling`); the lifecycle test passes 20 runs in a row.
- [x] `make check` green (644 passed, 2026-10-27) and `make dist` clean; module docs, architecture, the system spec and CHANGELOG updated.
