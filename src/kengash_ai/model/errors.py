"""Errors that carry the exit code the CLI returns (system spec §6)."""


class KengashError(Exception):
    """Base error: a one-line message plus an exit code."""

    exit_code = 1


class UserError(KengashError):
    """Bad input, or a state the requested command cannot act on."""


class NeedsSetup(KengashError):
    """Missing install, sign-in or init, or a folder that needs adopting."""

    exit_code = 4


class NeedsUser(KengashError):
    """A decision only the user can make."""

    exit_code = 5


class WaitTimeout(KengashError):
    """A wait ran out of time; the work it waited for goes on."""

    exit_code = 3


class LoopBusy(KengashError):
    """Another conductor's live loop covers this scope (SP11 spec §4)."""

    exit_code = 6
