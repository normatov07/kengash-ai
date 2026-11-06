# cli

## Purpose

Typer command surface for `kengash` (0.1.0's `harness` and `hrn` warned through 0.2.x and are gone in 0.3.0): parses arguments and formats output. From sub-project 2 on, every action is delegated to `ops`. Every `--project/-p` takes a project name or a folder inside a registered repo; one option callback (`workspace.project_slug`) turns it into the slug before a command runs, and a folder no project holds exits 4 naming `kengash init` (SP9).

## Interface

- `kengash --version` prints `kengash-ai <version>` and exits 0. Skills use this line to confirm the right binary is on PATH; `doctor` also accepts an older install's `super-harness <version>`.
- `kengash --help` lists commands and options.
- `run ID... [--steps N]` (`started <id> <step>→<provider>` / `skipped <id>: <reason>`; exit 1 when none started, 4 when a provider needs setup), `approve ID [--loops N] [--tokens N]`, `park ID --why W`, `stop ID`, `pause` and `resume` (`--project`), `ticket changes ID [--diff]` (`<path> +a -r  loop n <step> <provider>/<model>`), `ticket attach ID [--role R]` (the resume command), `wait [--timeout 540]` (`<id> <status> loop n/max: <detail>`, `plan <id> round r/max: <verdict>, <summary>` for plan reviews, `<id> queued loop n/max: <title>` for a ticket that became ready, `idle`, exit 3 on timeout, exit 6 under another conductor's loop), `merge ID` (`merged <id>: N commits into <base>`; exit 1 when the main tree is dirty or off base, or on a conflict), each with `--json` (SP3 spec §10).
- `kengash init [PATH]`, `doctor [--fix] [--quiet] [--scan DIR]`, `link SLUG NEW_PATH`, `adopt PATH`, each with `--json` (SP2 spec §3). `doctor` prints warnings as `[<slug>: ]warning: <message>`; it exits 1 only for problems that are neither fixed nor warnings.
- `kengash settings show|get KEY|check`, `memory add TEXT --why WHY [--section S|--decision [--rejected R]] [--by NAME]`, `memory show [--decisions]`, `memory compact [--timeout 540]` (`MEMORY.md N → M lines`; exit 1 with the reason when the result is kept out, 3 on timeout), `context`; all take `--project/-p` (default: the project containing the current folder) and `--json`. `settings get` prints strings plain and other values as JSON; `settings check` prints problems only.
- `kengash plan new --title T --mode grill|direct|quick` (prompt on stdin), `plan save ID` (`## Section` Markdown on stdin), `plan show ID`, `plan review ID [--timeout 540]` (`plan <id> round r: pass|fail, N findings`, a `warning:` line when the review ran on the conductor's provider, then the findings; exit 3 on timeout, 5 once the rounds are used up), `plan approve ID [--skip-review]`, `plan reject ID --why W`; id commands take `--project/-p` to narrow the search.
- `kengash ticket add --plan ID [--file F]` (YAML or JSON list, else stdin), `ticket show ID`, `ticket list [--folder F]`, `ticket find TEXT`, `ticket set ID KEY=VALUE…`, `ticket move ID FOLDER[/SUB] --why W`, `status [--project P]`; `list` and `find` cover the project here, else every project; `status` covers every project and prints at most 5 lines.
- `kengash next [--project P]`: tickets that can start now, one `<id> <project> <importance> <step>→<provider> <title>` line each, at most 5; otherwise why nothing can run (`--json`: everything, reasons included).
- `kengash agent new ROLE --kind read|edit|review --does TEXT [--cli P[/M]] [--step S] [--workflow W]… [--after STEP] [--send-back STEP] [--fallback P[/M],…] [--skill NAME | --instructions-file PATH|-] [-p SLUG] [--by] [--json]`: `added <role>: step <step> in <workflows>[; skill roles/<role>/SKILL.md]`; `kengash agent remove ROLE [-p SLUG]`: `removed <role>`; without `-p` both act on the defaults (SP6).
- `kengash agent edit ROLE [--cli] [--fallback] [--on|--off] [--blocking|--no-blocking] [--bypass-permissions|--no-bypass-permissions] [--kind] [--does] [--skill | --instructions-file PATH|-] [-p] [--json]`: `edited <role>: <keys>[; instructions roles/<role>/SKILL.md]`; a built-in agent refuses kind, does, skill and instructions. `kengash agent copy SOURCE NEW`: `copied <source> to <new>: step <step>`. `kengash agent show ROLE [--json]`: `<role> · built-in|yours · <kind> · step <step> · on|off`, then cli and fallbacks, switches, skill, `used in: <workflow> #<position>, …`, `does:`, a blank line and the instructions (SP10).
- `kengash workflow new NAME [--from W]` (`added workflow <name>`), `rename OLD NEW`, `remove NAME`, `route IMPORTANCE WORKFLOW` (`<importance> tickets run <workflow>`), `set NAME --steps a,b,c [--on-fail STEP=TARGET]…` (`set workflow <name>: a → b → c`); each takes `-p` and `--json` (SP10).
- `kengash skills lint [PATH…]`: one `<path>: <problem>` line per problem, exit 1 when any; default targets are the packaged installed and role skills; the command tree comes from the Typer app (SP4 spec decision 7). `make lint` runs it. `kengash skills install --agent A,… [--global] [--path DIR] [--cli-name N] [--yes]`: `<agent> <name>: installed|updated|unchanged|differs → <folder>[ (<note>)]` per skill, or `antigravity kengash (plugin): …` (capped), then the diffs of skills that differ; exit 5 until `--yes`. `kengash skills eval [SKILL] [--all] [--agent A,…] [--model M] [--baseline] [--dir D] [--keep D]`: `<skill>/<scenario> <agent>: pass|fail: <reason>` per run, then `transcripts: <folder>`; exit 1 on a failure, 4 when a named agent is missing or signed out. `make evals` runs every scenario. `kengash skills show NAME [--agent A]`: the skill as installed for the calling agent (default: the detected conductor), its references appended; exit 1 for an unknown name (SP11).
- `kengash ui open [--no-browser]` prints `http://127.0.0.1:<port>/?token=<token>` (exit 4 with the install line without the `[ui]` extra); `kengash ui stop` prints `stopped` or `not running`.
- Commands that change state take `--by NAME` (default `$HARNESS_AGENT`); stdin must be piped, never a terminal.

## Invariants

- Status and action commands print at most 5 lines by default; `--json` gives full output (spec §6).
- `loop claim [-p] [--take-over]` (`loop claimed: <scope>`; exit 6 `loop running: <agent> pid <pid> on <scope>, seen <age>; if that loop has ended: kengash loop claim --take-over`), `loop release [--force]` (`loop released: <scope>`, `no loop held here`, exit 1 `not released: N runnable; run: kengash next` or `not released: N ready, waiting for a slot; run: kengash wait`), `loop status [-p]` (a line per live lease, `loop running: …` or `this session holds the loop on <scope>`, else `no loop running`; then `loop_start: ask|auto`), each with `--json` (SP11 spec §4.8).
- Exit codes: 0 ok · 1 error · 2 usage · 3 wait timeout · 4 setup needed · 5 user decision needed · 6 another loop covers the scope.
- `cli` imports only `ops` and `model` (spec §3.1).

## Changes

- 2026-11-06 (final review): `wait` folds queued events into `queued: N tickets ready; run: kengash next` and points capped lines at `kengash status`.
- 2026-11-06: `loop claim|release|status`; exit 6; `wait` prints `queued` lines; `skills show` (SP11 M1).
- 2026-10-30: 0.3.0 drops the `harness` and `hrn` console scripts and `cli.legacy`, as 0.2.0 announced.
- 2026-10-30 (final review): `skills install` prints `note: …` lines (Claude Code's trust dialog for a project install); an `--instructions-file` that cannot be read exits 1 naming it.
- 2026-10-30: `agent edit|copy|show`, `agent new --fallback --skill --instructions-file`, the `workflow` group; help texts say `PROVIDER or PROVIDER/MODEL`, since Rich read `[/MODEL]` as markup and `agent new --help` crashed (SP10 M2).
- 2026-10-30: `skills install` prints a note after an entry, such as the agy plugin fallback (SP10 M1).
- 2026-10-27: `--project/-p` takes a project name or folder on every command (SP9).
- 2026-10-26: `skills install --cli-name` defaults to `kengash` and prints `removed` for an obsolete skill of ours (SP8).
- 2026-10-26: the command is `kengash` (0.2.0); `harness` and `hrn` run `cli.legacy`, which prints `harness is now kengash; the harness and hrn names stop working in 0.3.0` on stderr and runs the same app; `--by` reads `KENGASH_AGENT`, then `HARNESS_AGENT` (SP8).
- 2026-10-26: `init` and `link` print the `.kengash` link (SP8).
- 2026-10-26: every run first moves a 0.1.0 store once and prints the note on stderr (SP8).
- 2026-10-26: the package is `kengash_ai` (the app is Kengash AI, distributed as `kengash-ai`; SP7 spec decision 16).
- 2026-10-26: on native Windows every command exits 4 with "kengash runs on Linux and macOS; on Windows use WSL" (SP7).
- 2026-10-26: `agent new`, `agent remove` (SP6).
- 2026-10-23: `ui open`, `ui stop` (SP5 M1).
- 2026-10-23: `skills eval` (SP4 M2).
- 2026-10-23: `skills lint`, `skills install` (SP4 M1).
- 2026-10-23: `memory compact`; `memory add` reports a background compaction (SP3 M4).
- 2026-10-23: `plan review`; plan reviews in `wait` (SP3 M4).
- 2026-10-23: `ticket changes`, `ticket attach` (SP3 M3).
- 2026-10-23: `wait`; `doctor` reports dead workers (SP3 M3).
- 2026-10-23: `merge` (SP3 M3).
- 2026-10-23: `run`, `approve`, `park`, `stop`, `pause`, `resume` (SP3 M3).
- 2026-10-23: `doctor` warning lines and exit code (SP3 M2).
- 2026-10-22: `next` command (SP3 M1).
- 2026-10-22: `ticket` and `status` commands (SP2 M3).
- 2026-10-22: `plan` commands (SP2 M3).
- 2026-10-22: `--json` for `settings`, `memory` and `context`; `context` text is formatted here (SP2 M2 review).
- 2026-10-22: `settings`, `memory` and `context` commands (SP2 M2).
- 2026-10-22: `init`, `doctor`, `link`, `adopt` commands; errors print one stderr line with the spec exit code (SP2 M1).
- 2026-10-22: skeleton with `--version` and `--help`; console scripts `harness` and `hrn`.
