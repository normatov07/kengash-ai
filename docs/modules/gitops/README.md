# gitops

## Purpose

The git commands harness runs in the user's repo (SP3 spec §9): ticket worktrees, commits with `Harness-*` trailers, diffs, and later rebase and fast-forward merge. Never touches the store.

## Interface

- `ensure_worktree(repo, path, branch, base)` → `Worktree(path, branch, created)`: prunes stale worktree records, reuses `path` when it is already the worktree of `branch`, re-attaches an existing `branch`, else creates both from `base`. A foreign folder at `path` is a `GitError`.
- `commit_all(cwd, subject, trailers)` → new sha, or None when nothing changed: `git add -A`, then one commit whose message is the subject's first line and the trailers as `Key: value` lines.
- `head`, `current_branch` (None when detached), `is_clean` (tracked files only), `reset_soft(cwd, commit)`.
- `diff(cwd, base, stat=)` and `numstat(cwd, base)` → `FileChange(path, added, removed)` (None for binary files), both over `<base>...HEAD`.
- Errors: `GitError` (a `UserError`, exit 1) ends with git's last output line; `CommitFailed.output` holds everything a failing commit printed, hook output included.

## Invariants

- Imports only `model`.
- Plain `git`: the user's identity, signing and hooks apply; never `--no-verify`, never `-c` overrides, never a push.
- A commit subject keeps its first line only, so agent text cannot forge trailers.
- Serialising commands per repo (`repo-<slug>.lock`) is the caller's job.

## Changes

- 2026-10-23: worktrees, commits with trailers, diffs (SP3 M2).
