# cli

## Purpose

Typer command surface for `harness` (alias `hrn`): parses arguments and formats output. From sub-project 2 on, every action is delegated to `ops`.

## Interface

- `harness --version` prints `super-harness <version>` and exits 0. Skills use this line to confirm the right binary is on PATH.
- `harness --help` lists commands and options.
- `harness init [PATH]`, `doctor [--fix] [--quiet] [--scan DIR]`, `link SLUG NEW_PATH`, `adopt PATH`, each with `--json` (SP2 spec §3).
- `harness settings show|get KEY|check`, `memory add TEXT --why WHY [--section S|--decision [--rejected R]] [--by NAME]`, `memory show [--decisions]`, `context`; all take `--project/-p` (default: the project containing the current folder) and `--json`. `settings get` prints strings plain and other values as JSON; `settings check` prints problems only.
- `harness plan new --title T --mode grill|direct|quick` (prompt on stdin), `plan save ID` (`## Section` Markdown on stdin), `plan show ID`, `plan approve ID [--skip-review]`, `plan reject ID --why W`; id commands take `--project/-p` to narrow the search.
- `harness ticket add --plan ID [--file F]` (YAML or JSON list, else stdin), `ticket show ID`, `ticket list [--folder F]`, `ticket find TEXT`, `ticket set ID KEY=VALUE…`, `ticket move ID FOLDER[/SUB] --why W`, `status [--project SLUG]`; `list` and `find` cover the project here, else every project; `status` covers every project and prints at most 5 lines.
- `harness next [--project SLUG]`: tickets that can start now, one `<id> <project> <importance> <step>→<provider> <title>` line each, at most 5; otherwise why nothing can run (`--json`: everything, reasons included).
- Commands that change state take `--by NAME` (default `$HARNESS_AGENT`); stdin must be piped, never a terminal.

## Invariants

- Status and action commands print at most 5 lines by default; `--json` gives full output (spec §6).
- Exit codes: 0 ok · 1 error · 2 usage · 3 wait timeout · 4 setup needed · 5 user decision needed.
- `cli` imports only `ops` and `model` (spec §3.1).

## Changes

- 2026-10-22: `next` command (SP3 M1).
- 2026-10-22: `ticket` and `status` commands (SP2 M3).
- 2026-10-22: `plan` commands (SP2 M3).
- 2026-10-22: `--json` for `settings`, `memory` and `context`; `context` text is formatted here (SP2 M2 review).
- 2026-10-22: `settings`, `memory` and `context` commands (SP2 M2).
- 2026-10-22: `init`, `doctor`, `link`, `adopt` commands; errors print one stderr line with the spec exit code (SP2 M1).
- 2026-10-22: skeleton with `--version` and `--help`; console scripts `harness` and `hrn`.
