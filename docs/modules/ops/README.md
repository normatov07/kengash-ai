# ops

## Purpose

Use cases shared by the CLI and the UI. Each function takes plain arguments, works through `store` and `model`, and returns a dataclass the caller formats.

## Interface

- `projects.init_project(path)` → `InitResult`: registers the repo containing `path`, seeds its store folder, links `<repo>/.harness`, adds the exclude entry. Idempotent.
- `projects.relink(slug, new_path)` → `InitResult`: re-points a moved project.
- `projects.doctor(fix, scan)` → `DoctorReport`: one `Problem` per repo, link, exclude or document issue; `fix` repairs links and exclude entries only.
- `projects.adopt(path)` → `AdoptResult`: merges a real `.harness/` folder by uuid and archives the original.
- Errors are `model` errors and carry their exit code.

## Invariants

- Registry changes happen under `runtime/locks/registry.lock`; project changes under `runtime/locks/<slug>.lock`.
- Every state change ends with a store commit (`harness: <command> <slug>`).
- Adopt deletes nothing: the original folder and every losing copy end up in `projects/<slug>/archive/adopted-<stamp>/`.
- `ops` never imports `cli` or `ui`.

## Changes

- 2026-10-22: project use cases: init, relink, doctor, adopt (SP2 M1).
