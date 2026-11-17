"""Steward's own mount of the chat surface (``chat_surface.ChatSurface``):
the Chat section's page and the Illiana drawer on every app page, answering
as Illiana for the household. Every route but the page is the surface's
(``routes/partials/chat_surface.py``); the request gate already guards them.
"""

from fastapi import Request
from fastapi.responses import HTMLResponse, Response

from app.components.web_frontend import chat_surface
from app.components.web_frontend.chat_surface import ChatSurface
from app.components.web_frontend.nav import section
from app.components.web_frontend.rendering import render
from app.components.web_frontend.routes.partials.chat_surface import chat_router
from app.services.finance.service import STANDALONE_USER_ID

SECTION = section("chat")
# The history her conversations already list under (surface "finance").
STEWARD = ChatSurface(
    path=SECTION.path,
    user=STANDALONE_USER_ID,
    surface="finance",
    agent_slug="finance-assistant",
)


async def _signed_in() -> None:
    """The request gate (``middleware/request_gate.py``) has already let
    the request in; the surface needs no second guard."""


router = chat_router(STEWARD, _signed_in)


@router.get("", response_class=HTMLResponse, include_in_schema=False)
async def chat_page(request: Request) -> Response:
    """The Chat section: the page is the surface."""
    context = await chat_surface.surface_context(STEWARD)
    return render(request, "pages/chat.html", {"section": SECTION, **context})
