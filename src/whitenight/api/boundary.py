"""Local browser boundary, evaluated before any HTTP or WebSocket handler."""

from starlette.datastructures import Headers
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Receive, Scope, Send


class LocalBoundaryMiddleware:
    def __init__(self, app: ASGIApp, allowed_origins: list[str], testing: bool = False) -> None:
        self.app = app
        self.origins = frozenset(allowed_origins)
        self.hosts = {"127.0.0.1", "localhost", "[::1]"}
        if testing:
            self.hosts.add("testserver")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        host = headers.get("host", "").lower()
        hostname = host.split("]", 1)[0] + "]" if host.startswith("[") else host.split(":")[0]
        origin = headers.get("origin")
        bad_host = hostname not in self.hosts
        bad_origin = origin is not None and origin not in self.origins
        if scope["type"] == "websocket":
            if bad_host or bad_origin or origin is None:
                await send({"type": "websocket.close", "code": 1008})
                return
        elif bad_host or bad_origin:
            response = PlainTextResponse(
                "Untrusted host or origin", status_code=400 if bad_host else 403
            )
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)
