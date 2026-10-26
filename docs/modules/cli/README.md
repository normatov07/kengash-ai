# cli

## Purpose

Typer command surface for `harness` (alias `hrn`): parses arguments and formats output. From sub-project 2 on, every action is delegated to `ops`.

## Interface

- `harness --version` (also `hrn` and `kengash_ai`, the same app) prints `kengash-ai <version>` and exits 0. Skills use this line to confirm the right binary is on PATH; `doctor` also accepts an older install's `super-harness <version>`.
- `harness --help` lists commands and options.
- `run ID... [--steps N]` (`started <id> <step>→<provider>` / `skipped <id>: <reason>`; exit 1 when none started, 4 when a provider needs setup), `approve ID [--loops N] [--tokens N]`, `park ID --why W`, `stop ID`, `pause` and `resume` (`--project`), `ticket changes ID [--diff]` (`<path> +a -r  loop n <step> <provider>/<model>`), `ticket attach ID [--role R]` (the resume command), `wait [--timeout 540]` (`<id> <status> loop n/max: <detail>`, `plan <id> round r/max: <verdict>, <summary>` for plan reviews, `idle`, exit 3 on timeout), `merge ID` (`merged <id>: N commits into <base>`; exit 1 when the main tree is dirty or off base, or on a conflict), each with `--json` (SP3 spec §10).
- `harness init [PATH]`, `doctor [--fix] [--quiet] [--scan DIR]`, `link SLUG NEW_PATH`, `adopt PATH`, each with `--json` (SP2 spec §3). `doctor` prints warnings as `[<slug>: ]warning: <message>`; it exits 1 only for problems that are neither fixed nor warnings.
- `harness settings show|get KEY|check`, `memory add TEXT --why WHY [--section S|--decision [--rejected R]] [--by NAME]`, `memory show [--decisions]`, `memory compact [--timeout 540]` (`MEMORY.md N → M lines`; exit 1 with the reason when the result is kept out, 3 on timeout), `context`; all take `--project/-p` (default: the project containing the current folder) and `--json`. `settings get` prints strings plain and other values as JSON; `settings check` prints problems only.
- `harness plan new --title T --mode grill|direct|quick` (prompt on stdin), `plan save ID` (`## Section` Markdown on stdin), `plan show ID`, `plan review ID [--timeout 540]` (`plan <id> round r: pass|fail, N findings`, a `warning:` line when the review ran on the conductor's provider, then the findings; exit 3 on timeout, 5 once the rounds are used up), `plan approve ID [--skip-review]`, `plan reject ID --why W`; id commands take `--project/-p` to narrow the search.
- `harness ticket add --plan ID [--file F]` (YAML or JSON list, else stdin), `ticket show ID`, `ticket list [--folder F]`, `ticket find TEXT`, `ticket set ID KEY=VALUE…`, `ticket move ID FOLDER[/SUB] --why W`, `status [--project SLUG]`; `list` and `find` cover the project here, else every project; `status` covers every project and prints at most 5 lines.
- `harness next [--project SLUG]`: tickets that can start now, one `<id> <project> <importance> <step>→<provider> <title>` line each, at most 5; otherwise why nothing can run (`--json`: everything, reasons included).
- `harness agent new ROLE --kind read|edit|review --does TEXT [--cli P[/M]] [--step S] [--workflow W]… [--after STEP] [--send-back STEP] [-p SLUG] [--by] [--json]`: `added <role>: step <step> in <workflows>[; skill roles/<role>/SKILL.md]`; `harness agent remove ROLE [-p SLUG]`: `removed <role>`; without `-p` both act on the defaults (SP6).
- `harness skills lint [PATH…]`: one `<path>: <problem>` line per problem, exit 1 when any; default targets are the packaged installed and role skills; the command tree comes from the Typer app (SP4 spec decision 7). `make lint` runs it. `harness skills install --agent A,… [--global] [--path DIR] [--cli-name N] [--yes]`: `<agent> <name>: installed|updated|unchanged|differs → <folder>` per skill (capped), then the diffs of skills that differ; exit 5 until `--yes`. `harness skills eval [SKILL] [--all] [--agent A,…] [--model M] [--baseline] [--dir D] [--keep D]`: `<skill>/<scenario> <agent>: pass|fail: <reason>` per run, then `transcripts: <folder>`; exit 1 on a failure, 4 when a named agent is missing or signed out. `make evals` runs every scenario.
- `harness ui open [--no-browser]` prints `http://127.0.0.1:<port>/?token=<token>` (exit 4 with the install line without the `[ui]` extra); `harness ui stop` prints `stopped` or `not running`.
- Commands that change state take `--by NAME` (default `$HARNESS_AGENT`); stdin must be piped, never a terminal.

## Invariants

- Status and action commands print at most 5 lines by default; `--json` gives full output (spec §6).
- Exit codes: 0 ok · 1 error · 2 usage · 3 wait timeout · 4 setup needed · 5 user decision needed.
- `cli` imports only `ops` and `model` (spec §3.1).

## Changes

- 2026-10-26: every run first moves a 0.1.0 store once and prints the note on stderr (SP8).
- 2026-10-26: the package is `kengash_ai` (the app is Kengash AI, distributed as `kengash-ai`; SP7 spec decision 16).
- 2026-10-26: on native Windows every command exits 4 with "harness runs on Linux and macOS; on Windows use WSL" (SP7).
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
