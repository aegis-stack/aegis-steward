"""The Chat page's phone reaches a call: Steward's mount has its own socket
(``routes/chat.py``), not only the Overseer's. Without it the page's socket
met no route and the call bar said it could not reach the app."""

from __future__ import annotations

from fastapi.testclient import TestClient
import pytest
from starlette.websockets import WebSocketDisconnect

from app.components.web_frontend.routes.chat import STEWARD
from app.components.web_frontend.routes.partials import chat_live


async def _no_engine() -> tuple[None, None]:
    return None, None


def test_the_chat_pages_socket_answers(
    authenticated_app_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Answered by the call, which refuses with no engine on offer (1008),
    not turned away for want of a route."""
    monkeypatch.setattr(chat_live, "_engine_now", _no_engine)
    with (
        pytest.raises(WebSocketDisconnect) as refused,
        authenticated_app_client.websocket_connect(f"{STEWARD.path}/live/ws") as ws,
    ):
        ws.receive_json()
    assert refused.value.code == 1008
