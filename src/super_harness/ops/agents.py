"""Which CLI runs a role: its `cli`, then each `fallback` (SP3 spec decision 7)."""

from collections.abc import Callable, Collection
from dataclasses import dataclass
from functools import cache

from super_harness import adapters
from super_harness.model import NeedsSetup, ProviderStatus, Settings, split_cli
from super_harness.store.paths import StorePaths

UNSUPPORTED = adapters.UNSUPPORTED


@dataclass(frozen=True)
class Pick:
    role: str
    provider: str
    model: str | None
    fallback: bool


def pick(
    resolved: Settings,
    role: str,
    status: Callable[[str], ProviderStatus],
    *,
    skip: Collection[str] = (),
) -> Pick:
    """The first usable CLI of the role's chain that is not in `skip`; NeedsSetup if none."""
    agent = resolved.agents[role]
    first_problem: str | None = None
    for index, cli in enumerate([agent.cli, *agent.fallback]):
        provider, model = split_cli(cli)
        if provider == "shell":
            return Pick(role, provider, None, False)
        if provider in skip:
            continue
        found = problem(provider, status)
        if found is None:
            return Pick(role, provider, model, index > 0)
        first_problem = first_problem or found
    raise NeedsSetup(f"{role} cannot run: {first_problem or 'no other provider to fall back to'}")


def detector(paths: StorePaths) -> Callable[[str], ProviderStatus]:
    """Detect each provider once for the caller's lifetime."""

    @cache
    def detect(name: str) -> ProviderStatus:
        if name in UNSUPPORTED:
            return ProviderStatus(name=name, installed=False)
        return adapters.get(name, runtime=paths.runtime).detect()

    return detect


def problem(provider: str, status: Callable[[str], ProviderStatus]) -> str | None:
    """Why `provider` cannot run now, or None when it can."""
    if provider in UNSUPPORTED:
        return f"{provider} is not supported: {UNSUPPORTED[provider]}"
    found = status(provider)
    if not found.installed:
        return f"{provider} not installed; {found.hint}"
    if not found.signed_in:
        return f"{provider} signed out; {found.hint}"
    return None
