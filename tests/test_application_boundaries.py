"""Regression cases diagnosed with synthetic inputs before boundary changes."""

import asyncio
import io
import logging

import httpx
import pytest
from starlette.websockets import WebSocketDisconnect

from whitenight.logging_config import JsonFormatter, RedactingFilter
from whitenight.models.base import ModelProviderError, ProviderMessage
from whitenight.models.openai import OpenAIProvider


def test_foreign_host_and_origin_never_reach_application(client):
    assert client.get("/api/v1/sessions", headers={"host": "foreign.example"}).status_code == 400
    assert (
        client.post(
            "/api/v1/sessions", json={}, headers={"origin": "https://foreign.example"}
        ).status_code
        == 403
    )
    with (
        pytest.raises(WebSocketDisconnect),
        client.websocket_connect("/api/v1/chat/ws", headers={"origin": "https://foreign.example"}),
    ):
        pytest.fail("foreign websocket was accepted")


def test_websocket_requires_browser_origin(client):
    with pytest.raises(WebSocketDisconnect), client.websocket_connect("/api/v1/chat/ws"):
        pytest.fail("missing origin was accepted")


def test_provider_response_cannot_reflect_credentials():
    secret = "synthetic-credential-never-real"

    def reflect(request):
        return httpx.Response(400, text=request.headers["Authorization"])

    provider = OpenAIProvider(
        "https://synthetic.example/v1", "test", secret, transport=httpx.MockTransport(reflect)
    )

    async def run():
        with pytest.raises(ModelProviderError) as exc:
            async for _ in provider.stream_chat([ProviderMessage(role="user", content="hello")]):
                pass
        assert secret not in str(exc.value)

    asyncio.run(run())


def test_exception_output_does_not_include_untrusted_body():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(RedactingFilter())
    handler.setFormatter(JsonFormatter())
    log = logging.getLogger("boundary-fixture")
    log.addHandler(handler)
    try:
        try:
            raise ValueError("private-body-marker authorization: Bearer synthetic-secret")
        except ValueError:
            log.error("operation failed", exc_info=True)
        assert "private-body-marker" not in stream.getvalue()
        assert "synthetic-secret" not in stream.getvalue()
    finally:
        log.removeHandler(handler)
