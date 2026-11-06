"""Who is calling kengash: the conductor process (SP11 spec §4.1)."""

import os
import subprocess

import pytest

from kengash_ai.ops import conductors

TREE = {10: (9, "bash"), 9: (8, "claude"), 8: (1, "systemd")}


@pytest.fixture
def tree(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(conductors, "_ps", TREE.get)
    monkeypatch.setattr(os, "getppid", lambda: 10)
    monkeypatch.delenv("KENGASH_AGENT", raising=False)
    monkeypatch.delenv("HARNESS_AGENT", raising=False)


@pytest.mark.usefixtures("tree")
def test_conductor_finds_the_nearest_agent_ancestor() -> None:
    found = conductors.conductor()
    assert (found.pid, found.agent, found.command, found.detected) == (9, "claude", "claude", True)


@pytest.mark.usefixtures("tree")
def test_conductor_falls_back_to_the_parent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(TREE, 9, (8, "zsh"))
    found = conductors.conductor()
    assert (found.pid, found.agent, found.command, found.detected) == (10, "unknown", "bash", False)


@pytest.mark.usefixtures("tree")
def test_the_agent_variable_names_the_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KENGASH_AGENT", "codex")
    found = conductors.conductor()
    assert (found.pid, found.agent, found.detected) == (9, "codex", True)


def test_process_name_of_this_process_and_a_dead_one() -> None:
    assert conductors.process_name(os.getpid())
    done = subprocess.Popen(["true"])
    done.wait()
    assert conductors.process_name(done.pid) is None
