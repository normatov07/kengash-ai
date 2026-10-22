# cli

## Purpose

Typer command surface for `harness` (alias `hrn`): parses arguments and formats output. From sub-project 2 on, every action is delegated to `ops`.

## Interface

- `harness --version` prints `super-harness <version>` and exits 0. Skills use this line to confirm the right binary is on PATH.
- `harness --help` lists commands and options.

## Invariants

- Status and action commands print at most 5 lines by default; `--json` gives full output (spec §6).
- Exit codes: 0 ok · 1 error · 2 usage · 3 wait timeout · 4 setup needed · 5 user decision needed.
- `cli` imports only `ops` and `model` (spec §3.1).

## Changes

- 2026-10-22: skeleton with `--version` and `--help`; console scripts `harness` and `hrn`.
