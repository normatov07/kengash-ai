"""Git commands for ticket worktrees, commits, diffs, rebase and merge (SP3 spec §9).

Runs plain `git` in the user's repo, so the user's identity, signing and hooks apply.
"""

import subprocess
from dataclasses import dataclass
from pathlib import Path

from kengash_ai.model import UserError


class GitError(UserError):
    """A git command failed; the message ends with git's own last line."""


class CommitFailed(GitError):
    """`git commit` failed, usually in a hook; `output` holds everything git printed."""

    def __init__(self, message: str, output: str) -> None:
        super().__init__(message)
        self.output = output


@dataclass(frozen=True)
class Worktree:
    path: Path
    branch: str
    created: bool


@dataclass(frozen=True)
class FileChange:
    path: str
    added: int | None
    removed: int | None


@dataclass(frozen=True)
class Commit:
    sha: str
    subject: str
    trailers: dict[str, str]
    files: list[FileChange]


def ensure_worktree(repo: Path, path: Path, branch: str, base: str) -> Worktree:
    """Reuse the ticket's worktree, re-attach its branch, or create both from `base`."""
    _git(repo, "worktree", "prune")
    if path.exists():
        if _toplevel(path) == path.resolve() and current_branch(path) == branch:
            return Worktree(path, branch, created=False)
        raise GitError(f"{path} exists and is not the worktree of {branch}")
    path.parent.mkdir(parents=True, exist_ok=True)
    if branch_exists(repo, branch):
        _git(repo, "worktree", "add", "--quiet", str(path), branch)
    else:
        _git(repo, "worktree", "add", "--quiet", "-b", branch, str(path), base)
    return Worktree(path, branch, created=True)


def head(cwd: Path) -> str:
    return _git(cwd, "rev-parse", "HEAD").strip()


def current_branch(cwd: Path) -> str | None:
    """The checked-out branch; None on a detached HEAD."""
    result = _run(cwd, "symbolic-ref", "--short", "--quiet", "HEAD")
    return result.stdout.strip() if result.returncode == 0 else None


def is_clean(cwd: Path) -> bool:
    """No staged or unstaged changes to tracked files; untracked files do not count."""
    return _git(cwd, "status", "--porcelain", "--untracked-files=no") == ""


def reset_soft(cwd: Path, commit: str) -> None:
    _git(cwd, "reset", "--quiet", "--soft", commit)


def commit_all(cwd: Path, subject: str, trailers: dict[str, str]) -> str | None:
    """Commit every change with `trailers`; None when there is nothing to commit.

    Only the subject's first line is kept, so text from an agent cannot forge trailers.
    """
    _git(cwd, "add", "-A")
    if _run(cwd, "diff", "--cached", "--quiet").returncode == 0:
        return None
    lines = subject.strip().splitlines()
    message = lines[0].strip() if lines else ""
    if trailers:
        message += "\n\n" + "\n".join(f"{key}: {value}" for key, value in trailers.items())
    result = _run(cwd, "commit", "--quiet", "-F", "-", input=message + "\n")
    if result.returncode != 0:
        raise CommitFailed(_failure("commit", result), (result.stdout + result.stderr).strip())
    return head(cwd)


def diff(cwd: Path, base: str, *, stat: bool = False) -> str:
    """`git diff [--stat] <base>...HEAD`: what the branch changed since it left `base`."""
    return _git(cwd, "diff", *(["--stat"] if stat else []), f"{base}...HEAD")


def numstat(cwd: Path, base: str) -> list[FileChange]:
    return _numstat(_git(cwd, "diff", "--numstat", f"{base}...HEAD"))


def rebase(cwd: Path, base: str) -> list[str]:
    """Rebase the branch onto `base`: [] on success, else the conflicted paths after an abort."""
    result = _run(cwd, "rebase", "--quiet", base)
    if result.returncode == 0:
        return []
    conflicted = sorted(_git(cwd, "diff", "--name-only", "--diff-filter=U").splitlines())
    _run(cwd, "rebase", "--abort")
    if not conflicted:
        raise GitError(_failure("rebase", result))
    return conflicted


def catch_up(worktree: Path, base: str) -> bool:
    """Fast-forward a branch with no commits of its own to `base`, when its worktree has no
    uncommitted path at all (a failed attempt's edits stay where they are); True when HEAD
    moved (SP16 spec §3.11)."""
    if int(_git(worktree, "rev-list", "--count", f"{base}..HEAD").strip()):
        return False
    if changed_files(worktree):
        return False
    before = head(worktree)
    _git(worktree, "merge", "--ff-only", "--quiet", base)
    return head(worktree) != before


def contains(repo: Path, ancestor: str, ref: str) -> bool:
    """`ancestor` is reachable from `ref`: a fast-forward from `ancestor` to `ref` works."""
    return _run(repo, "merge-base", "--is-ancestor", ancestor, ref).returncode == 0


def merge_ff(repo: Path, branch: str, base: str) -> int:
    """Fast-forward `base` to `branch` in the main working tree; returns the commits merged."""
    current = current_branch(repo)
    if current != base:
        raise GitError(f"main working tree is on {current or 'a detached HEAD'}, not {base}")
    if not is_clean(repo):
        raise GitError("main working tree has uncommitted changes")
    count = int(_git(repo, "rev-list", "--count", f"{base}..{branch}").strip())
    _git(repo, "merge", "--ff-only", "--quiet", branch)
    return count


def remove_worktree(repo: Path, path: Path, branch: str) -> None:
    """Remove the ticket's worktree and delete its branch, whichever of them still exist."""
    if path.exists():
        _git(repo, "worktree", "remove", "--force", str(path))
    _git(repo, "worktree", "prune")
    if branch_exists(repo, branch):
        _git(repo, "branch", "-D", branch)


# Trailers on every ticket commit (`Kengash-Ticket`, `-Step`, `-Loop`, `-Agent`, `-Model`);
# 0.1.0 wrote them as `Harness-*` (SP8 spec decision 5)
TRAILER = "Kengash-"
LEGACY_TRAILER = "Harness-"


def _current(key: str) -> str:
    return TRAILER + key.removeprefix(LEGACY_TRAILER) if key.startswith(LEGACY_TRAILER) else key


def untracked_files(cwd: Path) -> list[str]:
    """Untracked paths in `cwd` that `.gitignore` does not hide, sorted."""
    out = _git(cwd, "ls-files", "--others", "--exclude-standard", "-z")
    return sorted(path for path in out.split("\0") if path)


def drop_untracked(cwd: Path, *, keep: set[str]) -> list[str]:
    """Remove untracked files that appeared since `keep` was listed (a check's output, such
    as flutter's golden failures), so they never reach a commit; returns what went."""
    gone = [path for path in untracked_files(cwd) if path not in keep]
    for path in gone:
        (cwd / path).unlink(missing_ok=True)
    return gone


def changed_files(cwd: Path) -> list[str]:
    """Uncommitted paths in `cwd`, tracked or not, sorted (SP12: where failed work is kept)."""
    entries = _git(cwd, "status", "--porcelain=v1", "-z", "--untracked-files=all").split("\0")
    found: list[str] = []
    skip = False
    for entry in entries:
        if skip:  # a rename's or copy's source path
            skip = False
            continue
        if len(entry) < 4:
            continue
        found.append(entry[3:])
        skip = entry[0] in "RC"
    return sorted(found)


def changed_between(cwd: Path, old: str, new: str) -> list[str]:
    """Paths that differ between two commits; [] when either is gone (SP17 spec §3.8)."""
    result = _run(cwd, "diff", "--name-only", old, new)
    return result.stdout.split("\n")[:-1] if result.returncode == 0 else []


def branch_files(cwd: Path, base: str) -> list[str]:
    """Every path the branch changed since it left `base`; a rename counts as both names."""
    return _git(cwd, "diff", "--name-only", "--no-renames", f"{base}...HEAD").splitlines()


def hot_files(
    repo: Path, ref: str, *, commits: int = 400, at_least: int = 3
) -> list[tuple[str, int]]:
    """Files that at least `at_least` tickets changed in the last `commits` commits, most
    changed first (SP18 spec §3.6). Tickets are counted, not commits: fix-up loops of one
    ticket do not make a file hot."""
    key = f"{TRAILER}Ticket"
    format_ = f"--format=%x00%(trailers:key={key},valueonly)"
    text = _git(repo, "log", f"-n{commits}", format_, "--name-only", ref)
    changed: dict[str, set[str]] = {}
    for chunk in text.split("\0")[1:]:
        names = [line.strip() for line in chunk.splitlines() if line.strip()]
        if len(names) > 1:  # a commit with no trailer has only file names, or nothing
            ticket = names[0]
            if len(ticket) == 36 and ticket.count("-") == 4:
                for name in names[1:]:
                    changed.setdefault(name, set()).add(ticket)
    found = [(name, len(tickets)) for name, tickets in changed.items() if len(tickets) >= at_least]
    return sorted(found, key=lambda item: (-item[1], item[0]))


def ticket_commits(repo: Path, ticket_uuid: str, ref: str) -> list[Commit]:
    """Commits on `ref` that carry `Kengash-Ticket: <uuid>` (or 0.1.0's `Harness-Ticket`),
    oldest first; their trailers come back under the `Kengash-` names."""
    greps = [f"--grep={prefix}Ticket: {ticket_uuid}" for prefix in (TRAILER, LEGACY_TRAILER)]
    shas = _git(repo, "log", "--reverse", "--fixed-strings", *greps, "--format=%H", ref).split()
    commits: list[Commit] = []
    for sha in shas:
        subject = _git(repo, "show", "-s", "--format=%s", sha).strip()
        raw = _git(repo, "show", "-s", "--format=%(trailers:only,unfold)", sha)
        trailers = {
            _current(key): value
            for key, value in (line.split(": ", 1) for line in raw.splitlines() if ": " in line)
        }
        commits.append(Commit(sha, subject, trailers, commit_files(repo, sha)))
    return commits


def branch_exists(repo: Path, branch: str) -> bool:
    return _run(repo, "show-ref", "--verify", "--quiet", f"refs/heads/{branch}").returncode == 0


def show(repo: Path, sha: str) -> str:
    """One commit's sha, subject and diff."""
    return _git(repo, "show", "--format=%H%n%s", sha)


def commit_files(cwd: Path, sha: str) -> list[FileChange]:
    """What one commit changed, per file."""
    return _numstat(_git(cwd, "show", "--numstat", "--format=", sha))


def _numstat(text: str) -> list[FileChange]:
    """Parse `--numstat` lines; binary files show `-` and become None."""
    changes: list[FileChange] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        added, removed, path = line.split("\t", 2)
        changes.append(
            FileChange(
                path,
                None if added == "-" else int(added),
                None if removed == "-" else int(removed),
            )
        )
    return changes


def _toplevel(path: Path) -> Path | None:
    result = _run(path, "rev-parse", "--show-toplevel")
    return Path(result.stdout.strip()).resolve() if result.returncode == 0 else None


def _run(cwd: Path, *args: str, input: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        input=input,
        capture_output=True,
        text=True,
        errors="replace",
        check=False,
    )


def _git(cwd: Path, *args: str) -> str:
    """Run git and return its stdout; GitError on failure."""
    result = _run(cwd, *args)
    if result.returncode != 0:
        raise GitError(_failure(args[0], result))
    return result.stdout


def _failure(subcommand: str, result: subprocess.CompletedProcess[str]) -> str:
    lines = (result.stderr or result.stdout).strip().splitlines()
    return f"git {subcommand} failed: {lines[-1] if lines else f'exit {result.returncode}'}"
