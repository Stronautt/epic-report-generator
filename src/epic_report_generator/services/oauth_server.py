"""Minimal local HTTP server to capture the OAuth 2.0 redirect callback."""

from __future__ import annotations

import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

logger = logging.getLogger(__name__)

_SUCCESS_HTML = """<!DOCTYPE html>
<html><head><title>Epic Report Generator</title>
<style>body{font-family:system-ui,sans-serif;display:flex;justify-content:center;
align-items:center;height:100vh;margin:0;background:#f4f5f7;color:#172b4d}
.card{text-align:center;padding:2rem 3rem;background:#fff;border-radius:8px;
box-shadow:0 1px 4px rgba(0,0,0,.15)}h1{margin:0 0 .5rem;font-size:1.5rem}
p{margin:0;color:#6b778c}</style></head>
<body><div class="card"><h1>&#10003; Authorized</h1>
<p>You can close this tab and return to the application.</p></div></body></html>"""

_ERROR_HTML = """<!DOCTYPE html>
<html><head><title>Epic Report Generator</title>
<style>body{font-family:system-ui,sans-serif;display:flex;justify-content:center;
align-items:center;height:100vh;margin:0;background:#f4f5f7;color:#172b4d}
.card{text-align:center;padding:2rem 3rem;background:#fff;border-radius:8px;
box-shadow:0 1px 4px rgba(0,0,0,.15)}h1{margin:0 0 .5rem;font-size:1.5rem;color:#de350b}
p{margin:0;color:#6b778c}</style></head>
<body><div class="card"><h1>&#10007; Authorization Failed</h1>
<p>%s</p></div></body></html>"""


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
            self._respond(400, _ERROR_HTML % desc)
            server.result = {"error": error, "error_description": desc}
            return

        code = params.get("code", [None])[0]
        state = params.get("state", [None])[0]

        if not code or not state:
            logger.warning("OAuth callback missing code or state parameter")
            self._respond(400, _ERROR_HTML % "Missing code or state parameter.")
            server.result = {"error": "missing_params"}
            return

        if state != server.expected_state:
            logger.error("OAuth state mismatch — possible CSRF attack")
            self._respond(400, _ERROR_HTML % "State mismatch — possible CSRF attack.")
            server.result = {"error": "state_mismatch"}
            return

        logger.info("OAuth callback received — authorization code captured")
        self._respond(200, _SUCCESS_HTML)
        server.result = {"code": code, "state": state}

    def _respond(self, status: int, html: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode())

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        """Suppress default stderr logging."""
        logger.debug("OAuth callback server: %s", format % args)


class OAuthCallbackServer(HTTPServer):
    """An HTTPServer that stores the callback result and auto-shuts down."""

    def __init__(self, port: int, expected_state: str) -> None:
        super().__init__(("127.0.0.1", port), OAuthCallbackHandler)
        self.expected_state = expected_state
        self.result: dict[str, str] | None = None
        self.timeout = 300  # 5 minutes max wait


def wait_for_callback(port: int, expected_state: str) -> dict[str, str] | None:
    """Start the callback server and block until a result is received.

    Returns the callback parameters dict or ``None`` on timeout.
    The server is started in a daemon thread so callers can cancel
    by shutting it down from another thread.
    """
    logger.info("Starting OAuth callback server on port %d (timeout=%ds)", port, 300)
    server = OAuthCallbackServer(port, expected_state)

    def _serve() -> None:
        server.handle_request()  # handle exactly one request then stop

    thread = threading.Thread(target=_serve, daemon=True)
    thread.start()
    thread.join(timeout=server.timeout)

    if thread.is_alive():
        logger.warning("OAuth callback timed out after %ds", server.timeout)
        server.shutdown()
        return None

    logger.debug("OAuth callback server stopped")
    return server.result
