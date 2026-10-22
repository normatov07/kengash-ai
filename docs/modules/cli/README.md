# cli

## Purpose

Typer command surface for `harness` (alias `hrn`): parses arguments and formats output. From sub-project 2 on, every action is delegated to `ops`.

## Interface

- `harness --version` prints `super-harness <version>` and exits 0. Skills use this line to confirm the right binary is on PATH.
- `harness --help` lists commands and options.
- `harness init [PATH]`, `doctor [--fix] [--quiet] [--scan DIR]`, `link SLUG NEW_PATH`, `adopt PATH`, each with `--json` (SP2 spec §3).
- `harness settings show|get KEY|check`, `memory add TEXT --why WHY [--section S|--decision [--rejected R]] [--by NAME]`, `memory show [--decisions]`, `context`; all take `--project/-p` (default: the project containing the current folder). `settings get` prints strings plain and other values as JSON; `settings check` prints problems only.

## Invariants

- Status and action commands print at most 5 lines by default; `--json` gives full output (spec §6).
- Exit codes: 0 ok · 1 error · 2 usage · 3 wait timeout · 4 setup needed · 5 user decision needed.
- `cli` imports only `ops` and `model` (spec §3.1).

## Changes

- 2026-10-22: `settings`, `memory` and `context` commands (SP2 M2).
- 2026-10-22: `init`, `doctor`, `link`, `adopt` commands; errors print one stderr line with the spec exit code (SP2 M1).
- 2026-10-22: skeleton with `--version` and `--help`; console scripts `harness` and `hrn`.
