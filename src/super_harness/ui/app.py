"""The UI's FastAPI app (SP5 spec decisions 3 to 6): static screens, a JSON API over
`ops`, and the journal as server-sent events, behind the run's token."""

import asyncio
import hmac
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from pathlib import Path
from typing import Literal, Protocol

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
from pydantic import BaseModel

from super_harness.model import HarnessError, JournalCursor, NeedsSetup, NeedsUser
from super_harness.ops import controls, merging, tickets, views

STATIC = Path(__file__).parent / "static"
COOKIE = "harness_token"
BY = "ui"
PING_S = 15.0
LOCKED = (
    "<!doctype html><title>harness</title>"
    "<p>Open the link that <code>harness ui open</code> printed.</p>"
)


class Action(BaseModel):
    """The body of a ticket action; each action reads the fields it needs."""

    loops: int | None = None
    tokens: int | None = None
    why: str = ""
    to: str = ""


class Connection(Protocol):
    async def is_disconnected(self) -> bool: ...


def create_app(*, token: str, port: int) -> FastAPI:
    """The app for one server run: `token` guards every API call, `port` the Host check."""
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    def authorized(request: Request) -> bool:
        given = request.cookies.get(COOKIE, "")
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
        if request.url.path.startswith("/api/"):
            if not authorized(request):
                return JSONResponse({"error": "missing or wrong token"}, status_code=401)
            if request.method != "GET" and request.headers.get("x-harness") != "1":
                return JSONResponse({"error": "missing X-Harness header"}, status_code=403)
        return await call_next(request)

    @app.exception_handler(HarnessError)
    async def harness_error(request: Request, exc: HarnessError) -> JSONResponse:
        status = 409 if isinstance(exc, NeedsSetup | NeedsUser) else 400
        return JSONResponse({"error": str(exc)}, status_code=status)

    @app.get("/", response_model=None)
    def index(request: Request, link: str | None = Query(None, alias="token")) -> Response:
        if link is not None:
            if not hmac.compare_digest(link.encode(), token.encode()):
                return HTMLResponse(LOCKED, status_code=401)
            response = RedirectResponse("/", status_code=303)
            response.set_cookie(COOKIE, token, httponly=True, samesite="strict", path="/")
            return response
        if not authorized(request):
            return HTMLResponse(LOCKED, status_code=401)
        return FileResponse(STATIC / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")

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

    @app.get("/api/events")
    def events(request: Request) -> StreamingResponse:
        stream = event_stream(request, views.journal_end())
        return StreamingResponse(stream, media_type="text/event-stream")

    return app


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
