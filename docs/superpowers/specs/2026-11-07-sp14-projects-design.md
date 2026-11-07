# SP14: Project hygiene, worktrees, forgetting projects and routed checks (design)

Date: 2026-11-07. Status: from the user's `kengash doctor --fix` output after upgrading to 0.4.0, and their "do all" to the four fixes proposed; calls marked *call* are the builder's.

## 1. Why

`kengash doctor` on the user's machine found:
1. Three projects, `main`, `saithe` and `spiderfish`, registered on 2026-11-06 from Orca workspaces. An Orca workspace is a git worktree of the user's `chess-samurai` repo at another path. Kengash matched a folder to a project only by path, so the loop skill, told `not a kengash project`, offered to register each workspace as a new project. Orca then deleted the workspaces, leaving three entries with missing repos and a duplicate draft plan. Kengash has no command to remove a project.
2. chess-samurai's workflows run `run_tests` last, after `review_code`, with no `on_fail` route: the UI's workflow editor added it on 2026-11-06. A failing `flutter test` therefore fails the ticket ("run_tests failed and has no on_fail step") instead of sending it back to `implement`, and the reviewer spends tokens before the tests run. `doctor` did not notice, because a `run_tests` step exists.

## 2. Decisions

1. **A worktree belongs to its repo's project.** `records.main_repo(folder)` is the repo whose `.git` is the folder's git common directory (`git rev-parse --path-format=absolute --git-common-dir`); for a normal checkout that is the checkout itself. `workspace.resolve_slug` and `workspace.project_slug` fall back to it when no registered path contains the folder, so every command run inside an Orca workspace, a `git worktree`, or a ticket's own worktree, works on the registered project. `kengash init` inside such a worktree registers nothing and says `<folder> is a worktree of <slug>; kengash uses <slug> here`. No `.kengash` link is made in the worktree (hard rule 3: one link per project) (*call*: commands reach the store without it).
2. **`kengash forget <project> [--yes]`** removes a project from kengash:
   - the registry entry, the store folder `projects/<slug>/` (plans, tickets, memory, settings), its ticket worktrees under `worktrees/<slug>/` (`git worktree remove --force` when the repo still exists, then `git worktree prune`; plain removal otherwise), the ticket state files, and the repo's `.kengash` link when it points at that store folder;
   - refused while a worker runs one of its tickets or a live loop lease names it: `stop them first`;
   - without `--yes` it prints what will go (path, plans, tickets, worktrees) and asks for the project name on a terminal; off a terminal it exits 5 (`add --yes`);
   - commits the store first, then journals `project.forgotten` (`plans`, `tickets`, `by`) and commits again, so the store's git history keeps every removed store file (`git -C ~/.kengash log`). Uncommitted changes in a ticket worktree, and unmerged ticket branches, are not in the store: they are lost, and the preview counts the worktrees that hold such changes.
   - `doctor`'s missing-repo line adds `; if it is gone for good: kengash forget <slug>`.
3. **A check step routes back.** In every workflow of a project, a step of kind `check` (`run_tests`, or a custom check) needs an `on_fail` target and must run before the reviews of the code it checks. The target is the last `edit` step before it (`implement`). `doctor` reports `project <slug>: workflow <name> runs <check> after <review>` and/or `with no way back to <edit>`, and `doctor --fix` (and `init`, through `hygiene.check_changes`) moves the check right after that edit step and sets `on_fail: {<check>: <edit>}`. A workflow without an edit step before its check is left alone.

## 3. Contract changes (system spec, same commit)

- §6: `kengash forget <project> [--yes]`; a folder inside a git worktree of a registered repo resolves to that project.
- §6.1: `project.forgotten`.
- `doctor`: the routed-check rule.

## 4. Exit criteria

Unit tests for `main_repo` (checkout, linked worktree, broken worktree, not a repo), resolution from a worktree, `init` in a worktree, `forget` (all removals, refusals, store history keeps the files), the routed-check report and fix (misplaced, unrouted, both, no edit step); `make check` green; on the user's store: chess-samurai's workflows fixed by `doctor --fix`, the three stale projects forgotten, `doctor` clean but for information notes.
