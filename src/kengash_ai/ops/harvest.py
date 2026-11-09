"""Memory harvest (SP18 spec §3): what the user settled reaches memory without anyone
remembering to write it. One detached one-shot job drains a spool; a harvest never fails
the command that asked for it."""

import contextlib
import json
import os
import re
import time
import traceback
from collections.abc import Mapping
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from kengash_ai import journal, memory, settings
from kengash_ai.model import (
    Event,
    HarvestCursors,
    HarvestEntry,
    HarvestFact,
    HarvestOutput,
    KengashError,
    SlotEntry,
    StepRequest,
    UserError,
    split_cli,
)
from kengash_ai.model.runtime import HarvestCursor
from kengash_ai.ops import agents, calls, compaction, jobs, prompts, records, slots
from kengash_ai.ops.workspace import resolve_slug
from kengash_ai.store import runtime
from kengash_ai.store.locks import locked
from kengash_ai.store.paths import StorePaths
from kengash_ai.store.redact import redact

ROLE = "harvester"
JOB = "harvest"
BY = memory.HARVESTED
MAX_FACTS = 8
MAX_CHARS = 16_000
MAX_ATTEMPTS = 3
MIN_WORDS = 4  # shorter text cannot settle anything worth a call
CHAT_MIN_WORDS = 8
QUOTE_WORDS = 2
KNOWN = 40  # newest decisions the harvester is shown
CONTEXT_CHARS = 400
CURSOR_DAYS = 30
SECTIONS = {
    "preference": "Preferences",
    "working_style": "Working style",
    "goal": "Goals",
    "turned_down": "Turned down",
}
ANSWERED = "User has answered"
PASTED = re.compile(r"<pasted_content[^>]*>(.*?)</pasted_content[^>]*>", re.DOTALL)
NOT_SAID = (  # text the CLI puts in a user message that the user did not type
    "<command-",
    "<local-command",
    "<system-reminder",
    "<task-notification",
    "<bash-",
    "<user-prompt-submit-hook",
    "Caveat:",
    "[Request interrupted",
    "Base directory for this skill",
)


@dataclass(frozen=True)
class ChatSlice:
    """Part of a transcript: `text` for the model, `quotable` the user's words alone."""

    text: str = ""
    quotable: str = ""


def submit(
    paths: StorePaths, source: str, project: str, text: str, quotable: str | None = None
) -> bool:
    """Queue `text` and start the job unless it runs already; False when nothing was queued.
    Never raises: the command that called this has already done its work."""
    try:
        return _submit(paths, source, project, text, text if quotable is None else quotable)
    except Exception:  # whatever went wrong here, the approval or reply already stands
        traceback.print_exc()
        return False


def _submit(paths: StorePaths, source: str, project: str, text: str, quotable: str) -> bool:
    if not paths.memory.is_dir() or len(quotable.split()) < MIN_WORDS:
        return False
    if settings.load(paths, project or None).memory.harvest == "off":
        return False
    entry = HarvestEntry(
        source=source,
        project=project,
        text=redact(text)[-MAX_CHARS:],
        quotable=redact(quotable)[-MAX_CHARS:],
    )
    with _lock(paths):
        runtime.save_harvest(paths, f"{time.time_ns()}-{uuid4().hex[:8]}", entry)
        if jobs.alive(paths, jobs.HARVEST) is None:
            _start(paths)
    return True


def _start(paths: StorePaths) -> None:
    """The detached worker; tests replace this."""
    jobs.start(paths, JOB, jobs.HARVEST, "", [JOB])


def plan_words(sections: Mapping[str, str]) -> str:
    """What the user approved in a plan; the Prompt comes last, so a cap at the tail keeps it."""
    names = ("Assumptions", "Decisions", "Prompt")
    return "\n\n".join(f"{name}:\n{sections[name]}" for name in names if sections.get(name))


def queue_plan(plan_id: str, project: str | None) -> bool:
    """`kengash memory harvest --plan`: queue a plan approved earlier."""
    paths = StorePaths.default()
    slug, path = records.locate_plan(paths, plan_id, project)
    return submit(paths, f"plan {plan_id}", slug, plan_words(records.load_plan(path).sections))


def run_harvest() -> str:
    """Drain the spool (the worker's job). Under the lock an empty spool ends the job, so an
    entry queued at that moment finds no worker and starts its own."""
    paths = StorePaths.default()
    tried: set[str] = set()
    added = 0
    while True:
        with _lock(paths):
            waiting = [item for item in runtime.harvest_entries(paths) if item[0] not in tried]
            if not waiting:
                jobs.forget(jobs.HARVEST)
                return f"harvest: {added} lines from {len(tried)} texts"
        name, entry = waiting[0]
        tried.add(name)
        added += _harvest(paths, name, entry)


def fail_harvest(reason: str) -> None:
    """End a harvest job that hit an unexpected error; its entries wait for the next one."""
    paths = StorePaths.default()
    slots.release(paths, jobs.HARVEST)
    with _lock(paths):
        journal.append(paths, jobs.exited(JOB, jobs.HARVEST, None, reason))
        jobs.forget(jobs.HARVEST)


def _harvest(paths: StorePaths, name: str, entry: HarvestEntry) -> int:
    """One entry: ask the model, keep what passes, and drop the entry; lines added."""
    try:
        resolved = settings.load(paths, entry.project or None)
    except KengashError as exc:
        return _failed(paths, name, entry, str(exc))
    if resolved.memory.harvest == "off":
        runtime.drop_harvest(paths, name)
        return 0
    provider, model = split_cli(resolved.memory.compactor)
    problem = agents.problem(provider, agents.detector(paths))
    if problem is not None:
        return _failed(paths, name, entry, problem)
    known = memory.decision_lines(paths, entry.project or None)[-KNOWN:]
    prompt = prompts.harvest_prompt(entry.text, known, memory.memory_lines(paths))
    slot = SlotEntry(provider=provider, project="", ticket=jobs.HARVEST, step=JOB, pid=os.getpid())
    jobs.take_slot(paths, slot)
    try:
        options = resolved.provider(provider)
        request = StepRequest(
            role=ROLE,
            cwd=paths.memory,
            prompt=prompt,
            output="harvest",
            profile="read_only",
            timeout_s=calls.step_timeout(resolved),
            log=_next_log(paths),
            model=model,
            session_id=str(uuid4()) if provider == "claude" else None,
            allow_api_key=options.allow_api_key,
            user_config=options.user_config,
        )
        called = calls.call(paths, provider, request, lambda: _next_log(paths))
    finally:
        slots.release(paths, jobs.HARVEST)
    result, output = called.result, called.result.output
    if result.error is not None or not isinstance(output, HarvestOutput):
        return _failed(paths, name, entry, calls.failure(provider, called.request, result))
    added, dropped = _apply(paths, entry, output.facts, known)
    runtime.drop_harvest(paths, name)
    usage = called.usage
    event: dict[str, Any] = {
        "type": "memory.harvested",
        "project": entry.project or None,
        "source": entry.source,
        "added": added,
        "dropped": dropped,
        "provider": provider,
        "model": model or "default",
        "tokens": {"in": usage.input, "out": usage.output},
        "by": BY,
    }
    journal.append(paths, Event.model_validate(event))
    return added


def _failed(paths: StorePaths, name: str, entry: HarvestEntry, reason: str) -> int:
    """Keep the entry for the next run, or drop it once it has used up its attempts."""
    attempts = entry.attempts + 1
    if attempts >= MAX_ATTEMPTS:
        runtime.drop_harvest(paths, name)
    else:
        runtime.save_harvest(paths, name, entry.model_copy(update={"attempts": attempts}))
    data = {
        "type": "memory.harvest_failed",
        "project": entry.project or None,
        "source": entry.source,
        "attempts": attempts,
        "reason": reason,
        "by": BY,
    }
    journal.append(paths, Event.model_validate(data))
    return 0


def _apply(
    paths: StorePaths, entry: HarvestEntry, facts: list[HarvestFact], known: list[str]
) -> tuple[int, int]:
    """Record each fact the user's own words back up: (added, dropped)."""
    added = dropped = 0
    for fact in facts[:MAX_FACTS]:
        if not quoted(fact.quote, entry.quotable):
            dropped += 1
            continue
        try:
            added += _record(paths, entry, fact, known)
        except UserError:
            dropped += 1
    return added, dropped + max(0, len(facts) - MAX_FACTS)


def quoted(quote: str, words: str) -> bool:
    """`quote` holds at least QUOTE_WORDS words and is in `words`, ignoring case and spacing."""
    wanted = " ".join(quote.casefold().split())
    return len(wanted.split()) >= QUOTE_WORDS and wanted in " ".join(words.casefold().split())


def _record(paths: StorePaths, entry: HarvestEntry, fact: HarvestFact, known: list[str]) -> int:
    """Write one fact where its kind belongs; 1 when a line was added."""
    project = entry.project or None
    why = fact.why.strip() or entry.source
    if fact.kind == "process":
        if project is None:
            raise UserError("a process note needs a project")
        return int(memory.add_process(paths, fact.fact, why=why, project=project, by=BY).added)
    if fact.kind == "decision":
        result = memory.add(
            paths,
            fact.fact,
            why,
            decision=True,
            rejected=fact.rejected.strip() or None,
            project=project,
            by=BY,
            user=True,
        )
        if result.added and 0 < fact.replaces <= len(known):
            memory.supersede(paths, known[fact.replaces - 1], by=BY)
        return int(result.added)
    result = memory.add(paths, fact.fact, why, section=SECTIONS[fact.kind], project=project, by=BY)
    if result.added and result.over_cap:
        compaction.start_background(paths)
    return int(result.added)


def from_hook(payload: str) -> None:
    """`kengash memory harvest --hook`: queue what the user said since the last time this
    session was read. Silent, and it never raises: it runs as a Claude Code hook."""
    with contextlib.suppress(Exception):
        _from_hook(payload)


def _from_hook(payload: str) -> None:
    if os.environ.get("KENGASH_AGENT"):  # a kengash worker's own session
        return
    data = json.loads(payload)
    session = str(data["session_id"])
    paths = StorePaths.default()
    slug = resolve_slug(None, Path(data["cwd"]), paths)
    if slug is None or settings.load(paths, slug).memory.harvest != "all":
        return
    with locked(paths.locks / "harvest-cursors.lock"):
        cursors = runtime.load_harvest_cursors(paths)
        known = cursors.sessions.get(session, HarvestCursor())
        said, offset = read_chat(Path(data["transcript_path"]), known.offset)
        cursors.sessions[session] = HarvestCursor(offset=offset)
        runtime.save_harvest_cursors(paths, _pruned(cursors))
    if len(said.quotable.split()) >= CHAT_MIN_WORDS:
        submit(paths, f"chat {session[:8]}", slug, said.text, said.quotable)


def _pruned(cursors: HarvestCursors) -> HarvestCursors:
    oldest = datetime.now(UTC) - timedelta(days=CURSOR_DAYS)
    kept = {key: value for key, value in cursors.sessions.items() if value.seen >= oldest}
    return HarvestCursors(sessions=kept)


def read_chat(path: Path, offset: int) -> tuple[ChatSlice, int]:
    """The user's messages after byte `offset` of a Claude Code transcript, and the new offset.
    A line still being written stays for the next read."""
    with path.open("rb") as transcript:
        transcript.seek(offset)
        data = transcript.read()
    end = data.rfind(b"\n") + 1
    shown: list[str] = []
    theirs: list[str] = []
    agent = ""
    for raw in data[:end].splitlines():
        try:
            item = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(item, dict) or item.get("isSidechain"):
            continue
        if item.get("type") == "assistant":
            agent = _agent_text(item) or agent
            continue
        said = _user_text(item)
        if said:
            if agent:
                shown.append(f"AGENT: {agent[-CONTEXT_CHARS:]}")
                agent = ""
            shown.append(f"USER: {said}")
            theirs.append(said)
    return ChatSlice("\n".join(shown), "\n".join(theirs)), offset + end


def _user_text(item: Mapping[str, Any]) -> str:
    """What the user typed or answered in one transcript line; "" for anything else."""
    if item.get("type") != "user" or item.get("isMeta") or item.get("isCompactSummary"):
        return ""
    content = (item.get("message") or {}).get("content")
    blocks = [{"type": "text", "text": content}] if isinstance(content, str) else content or []
    parts: list[str] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            parts.append(str(block.get("text", "")))
        elif block.get("type") == "tool_result" and _tool_text(block).startswith(ANSWERED):
            parts.append(_tool_text(block))
    kept = [_own_words(part) for part in parts if not part.lstrip().startswith(NOT_SAID)]
    return "\n".join(part for part in kept if part)


def _own_words(text: str) -> str:
    """What the user wrote around anything pasted, since a pasted document may carry words
    that are not theirs; a message that is nothing but a paste is theirs to send."""
    outside = PASTED.sub("", text).strip()
    return outside or "\n".join(part.strip() for part in PASTED.findall(text)).strip()


def _tool_text(block: Mapping[str, Any]) -> str:
    content = block.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(str(b.get("text", "")) for b in content if isinstance(b, dict))
    return ""


def _agent_text(item: Mapping[str, Any]) -> str:
    content = (item.get("message") or {}).get("content")
    if not isinstance(content, list):
        return ""
    texts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
    return "\n".join(str(text) for text in texts).strip()


def _lock(paths: StorePaths) -> AbstractContextManager[None]:
    """Orders a queued entry against the job's end, as compaction's lock does."""
    return locked(paths.locks / "harvest.lock")


def _next_log(paths: StorePaths) -> Path:
    state = runtime.load_ticket_state(paths, jobs.HARVEST)
    state.calls += 1
    runtime.save_ticket_state(paths, jobs.HARVEST, state)
    return paths.logs / f"{jobs.HARVEST}-{state.calls}.out"
