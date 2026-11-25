"""Splices the dashboard page's browser-side scripts into its HTML.

Flet renders to a canvas and runs no script of ours, so what the page
needs from the browser itself rides in here, ahead of Flutter's boot:

- **Paste capture.** Flet exposes no OS-clipboard image API (text only),
  so a pasted screenshot is caught in the browser and posted to the
  generic ``/api/v1/pastebox`` endpoint, where consumer surfaces drain it
  (see ``app/core/pastebox.py``).
- **The light/dark mode bridge** (#629). Overseer's mode is htmx's:
  htmx keeps it in ``localStorage["mode"]``, Flet's client storage keeps
  ``FLET_MODE_KEY`` under Flutter's ``flutter.`` prefix, each value
  JSON-encoded twice. The bridge copies htmx's choice across before
  Flutter reads it, and copies Overseer's toggle back as Flutter writes.
- **A refused socket renews the sign-in** (#647). The gate checks the
  sign-in only when the Flet socket opens, closing it when signed out,
  and Flet only retries. A socket that closes before it ever opened asks
  for the dashboard; a 401 renews through ``auth.js`` (loaded here, the
  htmx pages' one refresh), so Flet's next retry is let in, and only a
  failed renewal goes to the dashboard, which the gate sends to sign-in
  and back. A dead server (a restart) fails the ask, and Flet keeps
  retrying.

Injection over a vendored index.html on purpose: Flet's index markup
changes across versions, and a response-time splice keeps working
without carrying a copy of it.
"""

from __future__ import annotations

import json
from pathlib import Path

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.components.web_frontend.assets import static_url
from app.core.appearance import FLET_MODE_KEY, HTMX_MODE_KEY
from app.core.constants import DASHBOARD_PATH

# Posts every pasted image file; non-file pastes (plain text) fall
# through untouched so normal text paste keeps working.
_PASTE_SCRIPT = """<script>
document.addEventListener("paste", function (event) {
  var items = (event.clipboardData || {}).files || [];
  for (var i = 0; i < items.length; i++) {
    var file = items[i];
    if (!file.type || file.type.indexOf("image/") !== 0) continue;
    var form = new FormData();
    form.append("file", file, file.name || "pasted-image.png");
    fetch("/api/v1/pastebox/incoming", { method: "POST" }).finally(function () {
      fetch("/api/v1/pastebox", { method: "POST", body: form });
    });
  }
});
</script>"""

_MODE_SCRIPT = (
    """<script>
(function (htmxKey, fletKey) {
  try {
    var mode = localStorage.getItem(htmxKey);
    if (mode) localStorage.setItem(fletKey, JSON.stringify(JSON.stringify(mode)));
    var setItem = Storage.prototype.setItem;
    Storage.prototype.setItem = function (key, value) {
      setItem.call(this, key, value);
      if (key === fletKey) setItem.call(this, htmxKey, JSON.parse(JSON.parse(value)));
    };
  } catch (_) {
    /* storage disabled: Overseer keeps its own default */
  }
})("""
    + json.dumps(HTMX_MODE_KEY)
    + ", "
    + json.dumps(f"flutter.{FLET_MODE_KEY}")
    + """);
</script>"""
)

REFUSED_SOCKET_SCRIPT = (
    """<script>
(function (home) {
  window.WebSocket = new Proxy(window.WebSocket, {
    construct: function (Native, args) {
      var socket = Reflect.construct(Native, args);
      var opened = false;
      socket.addEventListener("open", function () { opened = true; });
      socket.addEventListener("close", function () {
        if (opened) return;
        fetch(home, { cache: "no-store" }).then(function (page) {
          if (page.status !== 401) return;
          _tryRefresh().then(function (ok) { if (!ok) location.assign(home); });
        }, function () {});
      });
      return socket;
    },
  });
})("""
    + json.dumps(f"{DASHBOARD_PATH}/")
    + """);
</script>"""
)


def _scripts() -> bytes:
    """Every script, ``auth.js`` first (the refused socket's renewal),
    named as the htmx pages name it, fingerprint included."""
    auth = f'<script src="{static_url("js/auth.js")}"></script>'
    return (auth + _PASTE_SCRIPT + _MODE_SCRIPT + REFUSED_SOCKET_SCRIPT).encode()


def inject_dashboard_scripts(body: bytes) -> bytes:
    """The pure splice: scripts before ``</head>``, or the body untouched
    when there is no head to splice into (non-HTML payloads)."""
    marker = b"</head>"
    if marker not in body:
        return body
    return body.replace(marker, _scripts() + marker, 1)


class DashboardScriptsMiddleware:
    """Wraps the dashboard app, buffering its HTML responses to splice the
    page scripts in.

    Pure ASGI (not ``BaseHTTPMiddleware``): the dashboard index is one
    small document, and buffering only happens for ``text/html`` - every
    other response streams through as-is.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        start_message: Message | None = None
        chunks: list[bytes] = []
        is_html = False

        async def send_injected(raw: bytes) -> None:
            """Release the stashed start plus the rewritten body."""
            body = inject_dashboard_scripts(raw)
            assert start_message is not None
            start_message["headers"] = [
                (k, v)
                for k, v in start_message["headers"]
                if k.lower() != b"content-length"
            ] + [(b"content-length", str(len(body)).encode())]
            await send(start_message)
            await send({"type": "http.response.body", "body": body})

        async def buffered_send(message: Message) -> None:
            nonlocal start_message, is_html
            if message["type"] == "http.response.start":
                headers = dict(message.get("headers") or [])
                is_html = b"text/html" in headers.get(b"content-type", b"")
                if not is_html:
                    await send(message)
                    return
                start_message = message
                return
            if message["type"] == "http.response.body" and is_html:
                chunks.append(message.get("body") or b"")
                if not message.get("more_body"):
                    await send_injected(b"".join(chunks))
                return
            if message["type"] == "http.response.pathsend" and is_html:
                # Servers that advertise ``http.response.pathsend`` get the
                # file path instead of its bytes, so the page never passes
                # through here to be rewritten. Read the one small document
                # and answer normally; every other asset under the mount
                # keeps the server's zero-copy send.
                await send_injected(Path(message["path"]).read_bytes())
                return
            await send(message)

        await self.app(scope, receive, buffered_send)
