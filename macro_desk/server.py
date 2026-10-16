"""Macro Desk MCP server.

Streamable HTTP on /mcp, stateless by default so it runs unchanged behind
Bedrock AgentCore Runtime, App Runner or any load balancer.

    python -m macro_desk.server            # 0.0.0.0:8000/mcp
    MACRO_DESK_TOKEN=secret python -m ...  # require "Authorization: Bearer secret"
"""

from __future__ import annotations

import hmac
import os
from pathlib import Path

import anyio
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from .catalog import INDICATORS
from .desk import Desk, UnknownIndicator

INSTRUCTIONS = """\
Macro Desk answers questions about the US economy and rates markets from live
FRED data. Every tool returns a `speech` field written to be read aloud as is:
say it verbatim or trim it, but do not add numbers that are not in the result.
Use macro_briefing for open questions ("what's going on in the economy"),
get_indicator for a specific release, shock_score for "is that a big number",
yield_curve for bonds and recession signals, macro_regime for the big picture.
"""

READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True,
                            open_world_hint=True)

mcp = MCPServer(
    name="macro-desk",
    title="Macro Desk",
    description="Voice-first US macro and rates briefings with shock scores, built on FRED.",
    instructions=INSTRUCTIONS,
    version="0.1.0",
)
desk = Desk()


async def _run(fn, *args):
    try:
        return await anyio.to_thread.run_sync(fn, *args)
    except UnknownIndicator as exc:
        raise ToolError(str(exc)) from exc


@mcp.tool(annotations=READ_ONLY)
async def macro_briefing() -> dict:
    """A 30-second spoken rundown of the US economy: the releases that moved the most
    against their own history, the shape of the yield curve, and the growth/inflation
    regime. Use for "brief me", "what's happening in the economy", "morning update"."""
    return await _run(desk.briefing)


@mcp.tool(annotations=READ_ONLY)
async def get_indicator(indicator: str) -> dict:
    """Latest reading for one US indicator in plain words, e.g. "inflation", "core PCE",
    "jobs report", "unemployment", "retail sales", "jobless claims", "GDP", "fed funds",
    "ten year yield", "breakevens". Mentions the shock score only when the move was unusual."""
    return await _run(desk.indicator, indicator)


@mcp.tool(annotations=READ_ONLY)
async def shock_score(indicator: str) -> dict:
    """How unusual the latest move was: z-score against the prior three years, its
    percentile in history, and the last time a move this large happened. Use for
    "is that a lot", "how big a surprise was the CPI print"."""
    return await _run(desk.shock, indicator)


@mcp.tool(annotations=READ_ONLY)
async def yield_curve() -> dict:
    """US Treasury curve: 3-month, 2-year and 10-year yields, 10y-3m and 10y-2y spreads,
    whether the curve is inverted and since when, and the 10-year's one-month move."""
    return await _run(desk.curve)


@mcp.tool(annotations=READ_ONLY)
async def macro_regime() -> dict:
    """Which growth/inflation quadrant the economy is in (goldilocks, reflation,
    stagflation, disinflationary slowdown), how long it has been there, and what came before."""
    return await _run(desk.regime)


@mcp.tool(annotations=READ_ONLY)
async def list_indicators() -> dict:
    """Everything Macro Desk can report on, with the phrases that map to each."""
    return await _run(desk.indicators)


CONSOLE = Path(__file__).parent / "web" / "index.html"


@mcp.custom_route("/", methods=["GET"])
async def console(_: Request) -> HTMLResponse:
    """Browser voice console that talks to this server over MCP."""
    return HTMLResponse(CONSOLE.read_text())


@mcp.custom_route("/ping", methods=["GET"])
async def ping(_: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


class BearerAuth:
    """Optional static bearer token on /mcp. Health checks stay open."""

    def __init__(self, app: ASGIApp, token: str):
        self.app = app
        self.expected = f"Bearer {token}".encode()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["path"].startswith("/mcp"):
            got = dict(scope["headers"]).get(b"authorization", b"")
            if not hmac.compare_digest(got, self.expected):
                await PlainTextResponse("unauthorized", status_code=401)(scope, receive, send)
                return
        await self.app(scope, receive, send)


def build_app(stateless: bool = True, host: str = "0.0.0.0", warm: bool = True) -> ASGIApp:
    if warm:
        desk.store.keep_warm(sorted({i.series_id for i in INDICATORS.values()}))
    app: ASGIApp = mcp.streamable_http_app(stateless_http=stateless, host=host)
    token = os.getenv("MACRO_DESK_TOKEN")
    return BearerAuth(app, token) if token else app


def main() -> None:
    import uvicorn

    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(build_app(host=host), host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
