"""The UI's FastAPI app (SP5 spec decisions 3 to 6): static screens, a JSON API over
`ops`, and the journal as server-sent events, behind the run's token."""

import asyncio
import dataclasses
import hmac
import json
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from pathlib import Path
from typing import Any, Literal, Protocol

from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from kengash_ai.model import JournalCursor, KengashError, NeedsSetup, NeedsUser
from kengash_ai.ops import (
    activity,
    agent_config,
    changes,
    compaction,
    configure,
    controls,
    merging,
    plans,
    projects,
    tickets,
    views,
    workflows,
)

STATIC = Path(__file__).parent / "static"
COOKIE = "kengash_token_{port}"  # one per server: cookies ignore ports
BY = "ui"
PING_S = 15.0
# Sent with every response (SP7 spec decision 4). Inline style attributes are part of the
# screens' markup, so styles allow 'unsafe-inline'; scripts load from this server only.
SECURITY_HEADERS = {
    "content-security-policy": (
        "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; font-src 'self'; connect-src 'self'; base-uri 'none'; "
        "form-action 'self'; frame-ancestors 'none'"
    ),
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "no-referrer",  # the first request carries the token in its URL
    "cross-origin-opener-policy": "same-origin",
    "cross-origin-resource-policy": "same-origin",
    "permissions-policy": "camera=(), microphone=(), geolocation=()",
}
LOCKED = (
    "<!doctype html><title>kengash</title>"
    "<p>Open the link that <code>kengash ui open</code> printed.</p>"
)


class Action(BaseModel):
    """The body of a ticket action; each action reads the fields it needs."""

    loops: int | None = None
    tokens: int | None = None
    why: str = ""
    to: str = ""


class LinkAction(BaseModel):
    """The body of a link action: the project to re-link, or the folder to adopt."""

    project: str = ""
    path: str = ""


class SettingsChange(BaseModel):
    """The body of a settings save: dotted key → value; null removes the key from the scope."""

    changes: dict[str, Any]


class NewAgent(BaseModel):
    """The body of a new agent (SP6 spec §5): `agent_config.new_agent`'s arguments."""

    project: str = ""
    role: str
    kind: Literal["read", "edit", "review"]
    does: str
    cli: str = "claude"
    step: str | None = None
    workflows: list[str] = []
    after: str | None = None
    send_back: str | None = None
    fallback: list[str] = []
    skill: str | None = None
    instructions: str | None = None


class AgentPatchBody(BaseModel):
    """The fields of an agent edit (SP10 spec §6); a field left out stays as it is."""

    cli: str | None = None
    fallback: list[str] | None = None
    on: bool | None = None
    blocking: bool | None = None
    bypass_permissions: bool | None = None
    kind: Literal["read", "edit", "review"] | None = None
    does: str | None = None
    skill: str | None = None
    instructions: str | None = None


class AgentEdit(BaseModel):
    """The body of an agent edit: the scope and the patch."""

    project: str = ""
    patch: AgentPatchBody


class AgentCopy(BaseModel):
    """The body of an agent copy: the scope and the new role's name."""

    project: str = ""
    new: str


class NewWorkflow(BaseModel):
    """The body of a new workflow: a copy of `from`, or one implement step."""

    model_config = ConfigDict(populate_by_name=True)
    project: str = ""
    name: str
    from_: str | None = Field(None, alias="from")


class RenameWorkflow(BaseModel):
    """The body of a workflow rename."""

    project: str = ""
    new: str


class Scope(BaseModel):
    """A body naming the scope: a project, or empty for the defaults."""

    project: str = ""


class Connection(Protocol):
    async def is_disconnected(self) -> bool: ...


def create_app(*, token: str, port: int) -> FastAPI:
    """The app for one server run: `token` guards every API call, `port` the Host check."""
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
    cookie = COOKIE.format(port=port)
    origins = [f"http://{host}" for host in sorted(hosts)]

    def authorized(request: Request) -> bool:
        given = request.cookies.get(cookie, "")
        header = request.headers.get("authorization", "")
        if header.startswith("Bearer "):
            given = header.removeprefix("Bearer ")
        return hmac.compare_digest(given.encode(), token.encode())

    @app.middleware("http")
    async def guard(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.headers.get("host", "") not in hosts:
            return PlainTextResponse("forbidden host", status_code=403)
        if request.headers.get("origin", origins[0]) not in origins:
            return PlainTextResponse("forbidden origin", status_code=403)
        if request.url.path.startswith("/api/"):
            if not authorized(request):
                return JSONResponse({"error": "missing or wrong token"}, status_code=401)
            if request.method != "GET" and request.headers.get("x-kengash") != "1":
                return JSONResponse({"error": "missing X-Kengash header"}, status_code=403)
        response = await call_next(request)
        if request.url.path.startswith("/static/"):
            response.headers["cache-control"] = "no-cache"  # revalidate: an upgrade shows at once
        return response

    @app.middleware("http")
    async def secure(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # added after guard, so it is the outer one and guard's refusals get the headers too
        response = await call_next(request)
        response.headers.update(SECURITY_HEADERS)
        return response

    @app.exception_handler(KengashError)
    async def kengash_error(request: Request, exc: KengashError) -> JSONResponse:
        status = 409 if isinstance(exc, NeedsSetup | NeedsUser) else 400
        return JSONResponse({"error": str(exc)}, status_code=status)

    @app.get("/", response_model=None)
    def index(request: Request, link: str | None = Query(None, alias="token")) -> Response:
        if link is not None:
            if not hmac.compare_digest(link.encode(), token.encode()):
                return HTMLResponse(LOCKED, status_code=401)
            response = RedirectResponse("/", status_code=303)
            response.set_cookie(cookie, token, httponly=True, samesite="strict", path="/")
            return response
        if not authorized(request):
            return HTMLResponse(LOCKED, status_code=401)
        return FileResponse(STATIC / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/api/meta")
    def meta() -> dict[str, str]:
        return {"version": views.version()}

    @app.get("/api/overview")
    def overview(window: Literal["today", "7d", "all"] = "today") -> views.Overview:
        return views.overview(window=window)

    @app.get("/api/board")
    def board(project: str | None = None) -> views.Board:
        return views.board(project=project)

    @app.post("/api/pause")
    def pause(project: str | None = None) -> controls.Paused:
        return controls.pause(project, by=BY)

    @app.post("/api/resume")
    def resume(project: str | None = None) -> controls.Resumed:
        return controls.resume(project, by=BY)

    @app.get("/api/tickets/{ticket_id}")
    def ticket_view(ticket_id: str) -> views.TicketView:
        return views.ticket_view(ticket_id=ticket_id, project=None)

    @app.get("/api/tickets/{ticket_id}/diff")
    def ticket_diff(ticket_id: str) -> changes.Changes:
        return changes.ticket_changes(ticket_id, diff=True, project=None)

    @app.get("/api/plans/{plan_id}")
    def plan_view(plan_id: str) -> dict[str, Any]:
        found = plans.show_plan(plan_id, project=None)
        return {"project": found.project, "meta": found.meta, "sections": found.sections}

    @app.post("/api/tickets/{ticket_id}/{action}")
    def ticket_action(ticket_id: str, action: str, body: Action | None = None) -> object:
        body = body or Action()
        if action == "approve":
            return controls.approve_ticket(
                ticket_id, loops=body.loops, tokens=body.tokens, project=None, by=BY
            )
        if action == "park":
            return controls.park_ticket(ticket_id, body.why, project=None, by=BY)
        if action == "run":
            return controls.run_tickets([ticket_id], by=BY)
        if action == "stop":
            return {"status": controls.stop_ticket(ticket_id, project=None, by=BY)}
        if action == "merge":
            return merging.merge_ticket(ticket_id, project=None, by=BY)
        if action == "move":
            return tickets.move_ticket(ticket_id, body.to, body.why, project=None, by=BY)
        raise HTTPException(status_code=404, detail=f"unknown action {action}")

    @app.get("/api/links")
    def link_health() -> views.Links:
        return views.links()

    @app.post("/api/links/repair")
    def repair_links() -> views.Links:
        projects.doctor(fix=True)  # what `kengash doctor --fix` does, links included
        return views.links()

    @app.post("/api/links/relink")
    def relink(body: LinkAction) -> views.Links:
        projects.relink(body.project, Path(body.path).expanduser())
        return views.links()

    @app.post("/api/links/adopt")
    def adopt(body: LinkAction) -> views.Links:
        projects.adopt(Path(body.path).expanduser())
        return views.links()

    @app.get("/api/agents")
    def agents_view(
        project: str = "",
        window: Literal["today", "7d", "all"] = "today",
        refresh: bool = False,
        detect: bool = True,
    ) -> views.AgentsView:
        return views.agents_view(
            project=project or None, window=window, refresh=refresh, detect=detect
        )

    @app.post("/api/agents")
    def new_agent(body: NewAgent) -> views.AgentsView:
        project = body.project or None
        agent_config.new_agent(
            body.role,
            kind=body.kind,
            does=body.does,
            cli=body.cli,
            step=body.step,
            workflows=body.workflows,
            after=body.after,
            send_back=body.send_back,
            fallback=body.fallback,
            skill=body.skill,
            instructions=body.instructions,
            project=project,
            by=BY,
        )
        return views.agents_view(project=project, detect=False)

    @app.post("/api/agents/{role}")
    def edit_agent(role: str, body: AgentEdit) -> views.AgentsView:
        project = body.project or None
        patch = agent_config.AgentPatch(**body.patch.model_dump())
        agent_config.edit_agent(role, patch, project=project, by=BY)
        return views.agents_view(project=project, detect=False)

    @app.post("/api/agents/{role}/copy")
    def copy_agent(role: str, body: AgentCopy) -> views.AgentsView:
        project = body.project or None
        agent_config.copy_agent(role, body.new, project=project, by=BY)
        return views.agents_view(project=project, detect=False)

    @app.post("/api/agents/{role}/remove")
    def remove_agent(role: str, body: Scope) -> views.AgentsView:
        agent_config.remove_agent(role, project=body.project or None, by=BY)
        return views.agents_view(project=body.project or None, detect=False)

    @app.get("/api/skills/{name}")
    def skill_text(name: str, project: str = "") -> views.SkillText:
        return views.skill_text(project=project or None, name=name)

    @app.get("/api/workflows")
    def workflows_view(project: str = "") -> views.WorkflowsView:
        return views.workflows_view(project=project or None)

    @app.post("/api/workflows")
    def new_workflow(body: NewWorkflow) -> views.WorkflowsView:
        project = body.project or None
        workflows.new_workflow(body.name, from_=body.from_, project=project, by=BY)
        return views.workflows_view(project=project)

    @app.post("/api/workflows/{name}/rename")
    def rename_workflow(name: str, body: RenameWorkflow) -> views.WorkflowsView:
        project = body.project or None
        workflows.rename_workflow(name, body.new, project=project, by=BY)
        return views.workflows_view(project=project)

    @app.post("/api/workflows/{name}/remove")
    def remove_workflow(name: str, body: Scope) -> views.WorkflowsView:
        project = body.project or None
        workflows.remove_workflow(name, project=project, by=BY)
        return views.workflows_view(project=project)

    @app.get("/api/memory")
    def memory_view(project: str = "") -> views.MemoryView:
        return views.memory_view(project=project or None)

    @app.post("/api/memory/compact")
    def compact() -> dict[str, bool]:
        return {"started": compaction.start_checked()}

    @app.get("/api/settings")
    def settings_view(project: str = "") -> views.SettingsView:
        return views.settings_view(project=project or None)

    @app.post("/api/settings")
    def save_settings(body: SettingsChange, project: str = "") -> views.SettingsView:
        configure.save_settings(body.changes, project=project or None, by=BY)
        return views.settings_view(project=project or None)

    @app.get("/api/tickets/{ticket_id}/live")
    def ticket_live(request: Request, ticket_id: str) -> StreamingResponse:
        stream = live_stream(request, activity.watch(ticket_id, None, heartbeat=True))
        return StreamingResponse(stream, media_type="text/event-stream")

    @app.get("/api/events")
    def events(request: Request) -> StreamingResponse:
        stream = event_stream(request, views.journal_end())
        return StreamingResponse(stream, media_type="text/event-stream")

    return app


async def live_stream(
    request: Connection, items: Iterator[activity.Activity | None]
) -> AsyncIterator[str]:
    """A ticket's worker activity as `event: activity` messages, history first, then live,
    ending with `event: done` once the ticket stops running (SP12 spec §4.5). Heartbeats
    (None) let the stream notice a closed tab within a poll, and keep proxies awake."""
    end = object()
    quiet = 0
    while not await request.is_disconnected():
        item = await asyncio.to_thread(next, items, end)
        if item is end:
            yield "event: done\ndata: {}\n\n"
            return
        if not isinstance(item, activity.Activity):  # a heartbeat
            quiet += 1
            if quiet % 15 == 0:
                yield ": ping\n\n"
            continue
        quiet = 0
        data = json.dumps(dataclasses.asdict(item), default=str)
        yield f"event: activity\ndata: {data}\n\n"


async def event_stream(
    request: Connection, cursor: JournalCursor, *, poll_s: float = 1.0
) -> AsyncIterator[str]:
    """New journal events as `event: journal` messages, with a ping every PING_S."""
    quiet = 0.0
    while not await request.is_disconnected():
        found, cursor = await asyncio.to_thread(views.events_after, cursor)
        for event in found:
            yield f"event: journal\ndata: {json.dumps(event, default=str)}\n\n"
        quiet = 0.0 if found else quiet + poll_s
        if quiet >= PING_S:
            quiet = 0.0
            yield ": ping\n\n"
        await asyncio.sleep(poll_s)
