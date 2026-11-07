# gitops

## Purpose

The git commands kengash runs in the user's repo (SP3 spec §9): ticket worktrees, commits with `Kengash-*` trailers (0.1.0 wrote `Harness-*`), diffs, rebase, fast-forward merge and a ticket's history. Never touches the store.

## Interface

- `ensure_worktree(repo, path, branch, base)` → `Worktree(path, branch, created)`: prunes stale worktree records, reuses `path` when it is already the worktree of `branch`, re-attaches an existing `branch`, else creates both from `base`. A foreign folder at `path` is a `GitError`.
- `commit_all(cwd, subject, trailers)` → new sha, or None when nothing changed: `git add -A`, then one commit whose message is the subject's first line and the trailers as `Key: value` lines.
- `head`, `current_branch` (None when detached), `is_clean` (tracked files only), `reset_soft(cwd, commit)`.
- `commit_files(cwd, sha)` → one commit's `FileChange`s; `show(repo, sha)` → its sha, subject and diff; `branch_exists(repo, branch)`.
- `diff(cwd, base, stat=)` and `numstat(cwd, base)` → `FileChange(path, added, removed)` (None for binary files), both over `<base>...HEAD`.
- `rebase(cwd, base)` → `[]`, or the conflicted paths after `git rebase --abort` (the branch is left as it was).
- `merge_ff(repo, branch, base)` → commits merged: refused unless the main working tree is on `base` with no tracked changes; `git merge --ff-only`.
- `remove_worktree(repo, path, branch)`: removes the worktree and deletes the branch, whichever still exist.
- `ticket_commits(repo, uuid, ref)` → `Commit(sha, subject, trailers, files)`, oldest first, found by `Harness-Ticket: <uuid>`; works on the base branch after the merge.
- Errors: `GitError` (a `UserError`, exit 1) ends with git's last output line; `CommitFailed.output` holds everything a failing commit printed, hook output included.

## Invariants

- Imports only `model`.
- Plain `git`: the user's identity, signing and hooks apply; never `--no-verify`, never `-c` overrides, never a push.
- A commit subject keeps its first line only, so agent text cannot forge trailers.
- Serialising commands per repo (`repo-<slug>.lock`) is the caller's job.

## Changes

- 2026-11-07: `catch_up(worktree, base)`: fast-forward a branch with no commits of its own to `base` when the worktree has no uncommitted path; True when HEAD moved (SP16).
- 2026-11-07: `untracked_files(cwd)` (not ignored) and `drop_untracked(cwd, keep=)`: remove files that appeared since `keep` was listed (SP15: what in-step checks leave behind).
- 2026-11-06: `changed_files(cwd)`: uncommitted paths, tracked or not, sorted (`git status --porcelain=v1 -z`) (SP12 M1).
- 2026-10-26: `TRAILER = "Kengash-"`; `ticket_commits` finds `Kengash-Ticket` or 0.1.0 `Harness-Ticket` commits and returns every trailer under its `Kengash-` name (SP8).
- 2026-10-26: the package is `kengash_ai` (the app is Kengash AI, distributed as `kengash-ai`; SP7 spec decision 16).
- 2026-10-23: `show`, `branch_exists` (SP3 M3).
- 2026-10-23: `commit_files` (SP3 M3).
- 2026-10-23: rebase, fast-forward merge, cleanup, ticket history (SP3 M2).
- 2026-10-23: worktrees, commits with trailers, diffs (SP3 M2).
