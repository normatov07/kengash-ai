"""Engine bookkeeping files under runtime/ (SP3 spec §4); never versioned."""

from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from kengash_ai.model.core import utc_now
from kengash_ai.model.steps import Usage


class _Runtime(BaseModel):
    # Fields a newer kengash added are ignored, not refused: a UI server or worker started
    # before an upgrade keeps reading files the new version writes (0.6.0 incident).
    model_config = ConfigDict(extra="ignore")


class SlotEntry(_Runtime):
    """A provider session one step holds, or waits for."""

    provider: str
    project: str
    ticket: str
    step: str
    pid: int
    since: datetime = Field(default_factory=utc_now)


class SlotTable(_Runtime):
    """runtime/slots.json: held slots, and waiting steps in arrival order."""

    held: list[SlotEntry] = Field(default_factory=list)
    waiting: list[SlotEntry] = Field(default_factory=list)


class Claims(_Runtime):
    """runtime/claims.json: when each project last had a ticket claimed."""

    last: dict[str, datetime] = Field(default_factory=dict)


class Trust(_Runtime):
    """runtime/trust.json: digest of each repo's hook and MCP files that doctor last reported."""

    seen: dict[str, str] = Field(default_factory=dict)


class WorkerRecord(_Runtime):
    """runtime/workers/<id>.json: one detached worker and its heartbeat (every 15 s)."""

    id: str
    project: str
    pid: int
    job: Literal["ticket", "plan-review", "compact"] = "ticket"
    step: str | None = None
    started: datetime = Field(default_factory=utc_now)
    heartbeat: datetime = Field(default_factory=utc_now)


class Running(_Runtime):
    """A CLI call in flight, so a dead worker's session can be recovered."""

    role: str
    provider: str
    model: str | None = None
    log: Path


class SentBack(_Runtime):
    """The step that sent a ticket back and its summary, or `user` and the answer given at a
    blocked gate; the next step's prompt says so (SP15 spec §3.4)."""

    step: str
    summary: str


class Checked(_Runtime):
    """Checks that passed inside `step` on `commit`, so `run_tests` can reuse them (SP15)."""

    commit: str
    step: str
    summary: str


class TicketState(_Runtime):
    """runtime/tickets/<id>.json: engine bookkeeping for one ticket; losing it only
    restarts stall counting."""

    streaks: dict[str, dict[str, int]] = Field(default_factory=dict)
    plan_rounds: int = 0
    approval: Literal["loop_cap", "token_cap", "approve_step", "blocked"] | None = None
    start_commit: str | None = None
    totals: dict[str, Usage] = Field(default_factory=dict)
    running: Running | None = None
    calls: int = 0
    sent_back: SentBack | None = None
    checked: Checked | None = None
    waiting_on: str = ""  # the ticket whose paths this one waits for (SP16 spec §3.8)
    split: bool = False  # a ticket splits once (SP17 spec §3.6)
    seen: dict[str, str] = Field(default_factory=dict)  # role → commit it last saw (SP17)


class RelayIntent(_Runtime):
    """runtime/relay.json: what a loop was asked to cover (`all` or project slugs), so a
    finishing worker starts the next ticket with no conductor awake (SP17 spec §3.4)."""

    scopes: list[str] = Field(default_factory=list)
    touched: datetime = Field(default_factory=utc_now)  # a claim, or the last ticket it started


class ConductorPing(_Runtime):
    """runtime/conductors/<pid>.json: a conductor that ran `next` or `wait`."""

    pid: int
    agent: str
    project: str | None
    time: datetime = Field(default_factory=utc_now)


class LoopLease(_Runtime):
    """runtime/loops/<pid>.json: the conductor running a loop over one project or all (SP11)."""

    pid: int
    agent: str
    command: str = ""  # the process name at claim time; a reused pid runs something else
    project: str | None = None  # None: every project
    started: datetime = Field(default_factory=utc_now)
    seen: datetime = Field(default_factory=utc_now)


class UiRecord(_Runtime):
    """runtime/ui.json: the running UI server (mode 0600: it holds the run's token)."""

    pid: int
    port: int
    token: str
    started: datetime = Field(default_factory=utc_now)
    version: str = ""  # the kengash-ai that started it; another version gets a new server


class JournalCursor(_Runtime):
    """A journal position: the day file last read and how many of its lines were read."""

    day: str = ""
    line: int = 0


class ViewerRecord(_Runtime):
    """runtime/viewers/<key>.json: a viewer tab's process (SP13); `pid` None while the tab
    that will run it is opening."""

    key: str
    pid: int | None = None
    since: datetime = Field(default_factory=utc_now)
