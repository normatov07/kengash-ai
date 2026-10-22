# ops

## Purpose

Use cases shared by the CLI and the UI. Each function takes plain arguments, works through `store`, `model` and the `settings`, `memory` and `journal` units, and returns a dataclass the caller formats.

## Interface

- `projects.init_project(path)` → `InitResult`: registers the repo containing `path`, seeds its store folder, links `<repo>/.harness`, adds the exclude entry. Idempotent.
- `projects.relink(slug, new_path)` → `InitResult`: re-points a moved project.
- `projects.doctor(fix, scan)` → `DoctorReport`: one `Problem` per repo, link, exclude or document issue; `fix` repairs links and exclude entries only.
- `projects.adopt(path)` → `AdoptResult`: merges a real `.harness/` folder by uuid and archives the original.
- `workspace`: `resolve_slug` (the named project, else the registered project containing the current folder), settings `settings_yaml`/`setting`/`settings_problems`, memory `remember`/`recall`, `context` → `Context(memory, project, process, gates)` (MEMORY.md, PROCESS.md headings, open gates) and `open_gates` → `OpenGate(id, sub_status, title)` items.
- `records`: `scope`, `locate_plan`, `locate_ticket` (ids are store-unique; `project` narrows the search), `taken_ids`, `project_tickets`, `load_plan`/`load_ticket` (schema errors become `UserError`), `document` → `Document(project, path, meta, sections, text)`, `describe`, `one_line`, `record` (journal the events, then commit).
- `plans`: `new_plan`, `save_plan`, `show_plan`, `approve_plan`, `reject_plan` → `PlanResult(id, project, status, sections, review_skipped)`; approval needs a review verdict, a quick plan, `plan.review_max: 0`, or `skip_review`.
- `tickets`: `add_tickets` → `Batch(plan, project, tickets=[NewTicket(id, key, title, status)])`, `show_ticket` → `Document`, `list_tickets`/`find_tickets` → `TicketLine(id, project, status, importance, title)`; without a project they cover the project here, else every project.
- Errors are `model` errors and carry their exit code.

## Invariants

- Registry changes happen under `runtime/locks/registry.lock`; project, plan and ticket changes under `runtime/locks/<slug>.lock`, then journal events, then a store commit.
- Every state change ends with a store commit (`harness: <command> <slug>`).
- Adopt deletes nothing: the original folder and every losing copy end up in `projects/<slug>/archive/adopted-<stamp>/`.
- `ticket add` validates the whole batch (schema, keys, references, cycles, workflows) before writing any ticket; a ticket is `ready` only when every dependency is done.
- `ops` never imports `cli` or `ui`.

## Changes

- 2026-10-22: `tickets` add, show, list, find (SP2 M3).
- 2026-10-22: `records` and `plans` (SP2 M3).
- 2026-10-22: `context` returns a `Context` dataclass instead of text (SP2 M2 review).
- 2026-10-22: workspace use cases for settings, memory and context (SP2 M2).
- 2026-10-22: `relink` refuses a path already registered under another slug.
- 2026-10-22: project use cases: init, relink, doctor, adopt (SP2 M1).
