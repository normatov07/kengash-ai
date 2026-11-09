"""Which CLI runs a role: its `cli`, then each `fallback` (SP3 spec decision 7)."""

from collections.abc import Callable, Collection
from dataclasses import dataclass
from functools import cache

from kengash_ai import adapters
from kengash_ai.model import NeedsSetup, ProviderStatus, Settings, split_cli
from kengash_ai.store.paths import StorePaths


@dataclass(frozen=True)
class Pick:
    role: str
    provider: str
    model: str | None
    fallback: bool

    @property
    def cli(self) -> str:
        return f"{self.provider}/{self.model}" if self.model else self.provider


def pick(
    resolved: Settings,
    role: str,
    status: Callable[[str], ProviderStatus],
    *,
    skip: Collection[str] = (),
    importance: str | None = None,
) -> Pick:
    """The first usable CLI of the role's chain that is not in `skip` (a provider, or one
    provider/model); NeedsSetup if none. The chain is the CLI for the ticket's `importance`,
    the agent's CLI, then its fallbacks."""
    agent = resolved.agents[role]
    first_problem: str | None = None
    chain = list(dict.fromkeys([agent.cli_for(importance), agent.cli, *agent.fallback]))
    for index, cli in enumerate(chain):
        provider, model = split_cli(cli)
        if provider in skip or cli in skip:
            continue
        if provider == "shell":
            return Pick(role, provider, None, False)
        found = problem(provider, status) or _no_model(provider, model, status)
        if found is None:
            return Pick(role, provider, model, index > 0)
        first_problem = first_problem or found
    raise NeedsSetup(f"{role} cannot run: {first_problem or 'no other provider to fall back to'}")


def detector(paths: StorePaths) -> Callable[[str], ProviderStatus]:
    """Detect each provider once for the caller's lifetime."""

    @cache
    def detect(name: str) -> ProviderStatus:
        return adapters.get(name, runtime=paths.runtime).detect()

    return detect


def _no_model(
    provider: str, model: str | None, status: Callable[[str], ProviderStatus]
) -> str | None:
    """Why `model` cannot run, by the CLI's own list; aliases and an empty list say nothing."""
    found = status(provider)
    if model and found.live_models and found.models and model not in found.models:
        return f"{provider} has no model {model}; pick one on the Agents page"
    return None


def problem(provider: str, status: Callable[[str], ProviderStatus]) -> str | None:
    """Why `provider` cannot run now, or None when it can."""
    found = status(provider)
    if not found.installed:
        return f"{provider} not installed; {found.hint}"
    if not found.signed_in:
        return f"{provider} signed out; {found.hint}"
    return None
