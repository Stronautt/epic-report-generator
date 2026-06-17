"""Tests for epic_report_generator.services.oauth_server."""

from __future__ import annotations

import threading
import urllib.error
import urllib.parse
import urllib.request

from epic_report_generator.services.oauth_server import (
    OAuthCallbackServer,
    _error_page,
    _success_page,
)


def _start_server(port: int, state: str) -> OAuthCallbackServer:
    """Start the callback server in a daemon thread and return it."""
    server = OAuthCallbackServer(port, state)
    t = threading.Thread(target=server.handle_request, daemon=True)
    t.start()
    return server


def _get(url: str) -> tuple[int, str]:
    """Issue a GET request and return (status, body)."""
    try:
        with urllib.request.urlopen(url) as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode()


class TestCallbackSuccess:
    """A valid callback should capture the authorization code."""

    def test_valid_callback(self) -> None:
        state = "random-state-123"
        server = _start_server(0, state)
        port = server.server_address[1]

        status, body = _get(
            f"http://127.0.0.1:{port}/callback?code=AUTH_CODE&state={state}"
        )
        server.server_close()

        assert status == 200
        assert "Authorized" in body
        assert server.result is not None
        assert server.result["code"] == "AUTH_CODE"
        assert server.result["state"] == state


class TestStateMismatch:
    """A mismatched state parameter should be rejected (CSRF protection)."""

    def test_state_mismatch(self) -> None:
        server = _start_server(0, "expected")
        port = server.server_address[1]

        status, body = _get(f"http://127.0.0.1:{port}/callback?code=CODE&state=wrong")
        server.server_close()

        assert status == 400
        assert "CSRF" in body or "mismatch" in body.lower()
        assert server.result is not None
        assert server.result["error"] == "state_mismatch"


class TestMissingParams:
    """Missing code or state should be rejected."""

    def test_missing_code(self) -> None:
        server = _start_server(0, "s")
        port = server.server_address[1]

        status, _ = _get(f"http://127.0.0.1:{port}/callback?state=s")
        server.server_close()

        assert status == 400
        assert server.result is not None
        assert server.result["error"] == "missing_params"


class TestErrorCallback:
    """Atlassian may redirect with an error parameter."""

    def test_error_from_provider(self) -> None:
        server = _start_server(0, "s")
        port = server.server_address[1]

        url = (
            f"http://127.0.0.1:{port}/callback"
            "?error=access_denied&error_description=User+denied"
        )
        status, body = _get(url)
        server.server_close()

        assert status == 400
        assert "Authorization Failed" in body
        assert server.result is not None
        assert server.result["error"] == "access_denied"


class TestNonCallbackPath:
    """Requests to paths other than /callback should get a 404."""

    def test_wrong_path(self) -> None:
        server = _start_server(0, "s")
        port = server.server_address[1]

        status, _ = _get(f"http://127.0.0.1:{port}/other")
        server.server_close()

        assert status == 404


class TestErrorEscaping:
    """The provider error_description must be HTML-escaped (no reflected XSS)."""

    def test_error_page_escapes_message(self) -> None:
        html = _error_page("<script>alert(1)</script> & 'q'")
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;" in html

    def test_success_page_renders(self) -> None:
        assert "Authorized" in _success_page()

    def test_callback_error_description_is_escaped(self) -> None:
        server = _start_server(0, "s")
        port = server.server_address[1]

        desc = "<script>alert(1)</script>"
        url = (
            f"http://127.0.0.1:{port}/callback"
            f"?error=bad&error_description={urllib.parse.quote(desc)}"
        )
        status, body = _get(url)
        server.server_close()

        assert status == 400
        assert "<script>alert(1)</script>" not in body
        assert "&lt;script&gt;" in body
