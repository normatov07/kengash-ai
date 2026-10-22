"""Errors that carry the exit code the CLI returns (system spec §6)."""


class HarnessError(Exception):
    """Base error: a one-line message plus an exit code."""

    exit_code = 1


class UserError(HarnessError):
    """Bad input, or a state the requested command cannot act on."""


class NeedsSetup(HarnessError):
    """Missing install, sign-in or init, or a folder that needs adopting."""

    exit_code = 4


class NeedsUser(HarnessError):
    """A decision only the user can make."""

    exit_code = 5
