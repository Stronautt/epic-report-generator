"""Minimal local HTTP server to capture the OAuth 2.0 redirect callback."""

from __future__ import annotations

import html
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

logger = logging.getLogger(__name__)

_CALLBACK_TIMEOUT_S = 300  # 5 minutes max wait for the browser OAuth flow

_PAGE_HTML = """<!DOCTYPE html>
<html><head><title>Epic Report Generator</title>
<style>body{{font-family:system-ui,sans-serif;display:flex;justify-content:center;
align-items:center;height:100vh;margin:0;background:#f4f5f7;color:#172b4d}}
.card{{text-align:center;padding:2rem 3rem;background:#fff;border-radius:8px;
box-shadow:0 1px 4px rgba(0,0,0,.15)}}h1{{margin:0 0 .5rem;font-size:1.5rem;color:{h1_color}}}
p{{margin:0;color:#6b778c}}</style></head>
<body><div class="card"><h1>{heading}</h1>
<p>{body}</p></div></body></html>"""


def _success_page() -> str:
    return _PAGE_HTML.format(
        h1_color="#172b4d",
        heading="&#10003; Authorized",
        body="You can close this tab and return to the application.",
    )


def _error_page(message: str) -> str:
    """Build the error page, escaping the (possibly user-controlled) message."""
    return _PAGE_HTML.format(
        h1_color="#de350b",
        heading="&#10007; Authorization Failed",
        body=html.escape(message),
    )


class OAuthCallbackHandler(BaseHTTPRequestHandler):
    """Handle the OAuth redirect and extract the authorization code."""

    def do_GET(self) -> None:  # noqa: N802
        """Process the callback GET request from Atlassian."""
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        server: OAuthCallbackServer = self.server  # type: ignore[assignment]

        if parsed.path != "/callback":
            logger.debug("Ignoring request to %s", parsed.path)
            self.send_response(404)
            self.end_headers()
            return

        error = params.get("error", [None])[0]
        if error:
            desc = params.get("error_description", [error])[0]
            logger.error("OAuth callback error: %s — %s", error, desc)
            self._respond(400, _error_page(desc))
            server.result = {"error": error, "error_description": desc}
            return

        code = params.get("code", [None])[0]
        state = params.get("state", [None])[0]

        if not code or not state:
            logger.warning("OAuth callback missing code or state parameter")
            self._respond(400, _error_page("Missing code or state parameter."))
            server.result = {"error": "missing_params"}
            return

        if state != server.expected_state:
            logger.error("OAuth state mismatch — possible CSRF attack")
            self._respond(400, _error_page("State mismatch — possible CSRF attack."))
            server.result = {"error": "state_mismatch"}
            return

        logger.info("OAuth callback received — authorization code captured")
        self._respond(200, _success_page())
        server.result = {"code": code, "state": state}

    def _respond(self, status: int, body: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body.encode())

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        """Route BaseHTTPRequestHandler access logs to the Python logger."""
        logger.debug("OAuth callback server: %s", format % args)


class OAuthCallbackServer(HTTPServer):
    """An HTTPServer that stores the callback result and auto-shuts down."""

    # Set SO_REUSEADDR before binding so a quick re-login on the fixed callback
    # port (18492) does not hit EADDRINUSE while the previous socket lingers in
    # TIME_WAIT. socketserver reads this class attribute during server_bind().
    allow_reuse_address = True

    def __init__(self, port: int, expected_state: str) -> None:
        super().__init__(("127.0.0.1", port), OAuthCallbackHandler)
        self.expected_state = expected_state
        self.result: dict[str, str] | None = None
        self.timeout = _CALLBACK_TIMEOUT_S


def wait_for_callback(port: int, expected_state: str) -> dict[str, str] | None:
    """Start the callback server and block until a result is received.

    Returns the callback parameters dict or ``None`` on timeout.
    The server is started in a daemon thread so callers can cancel
    by shutting it down from another thread.
    """
    logger.info(
        "Starting OAuth callback server on port %d (timeout=%ds)",
        port,
        _CALLBACK_TIMEOUT_S,
    )
    server = OAuthCallbackServer(port, expected_state)

    def _serve() -> None:
        server.handle_request()  # handle exactly one request then stop

    thread = threading.Thread(target=_serve, daemon=True)
    thread.start()
    thread.join(timeout=server.timeout)

    if thread.is_alive():
        logger.warning("OAuth callback timed out after %ds", server.timeout)
        server.server_close()  # release the listening socket (shutdown() is a no-op here)
        return None

    logger.debug("OAuth callback server stopped")
    return server.result
