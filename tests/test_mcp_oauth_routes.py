"""Regression tests for MCP OAuth token-exchange error handling.

A cold connection to oauth2.googleapis.com raised httpx.ConnectTimeout, which
fell through to the generic exception handler and surfaced as an HTTP 500.
Network-level failures must return a graceful 4xx HTML page instead.
"""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest

import routes.mcp_routes as mcp_routes


def _fake_server(tmp_path):
    keys_file = tmp_path / "keys.json"
    keys_file.write_text(json.dumps(
        {"installed": {"client_id": "id", "client_secret": "secret"}}
    ), encoding="utf-8")
    return SimpleNamespace(
        id="srv1",
        name="Test Server",
        oauth_config=json.dumps({
            "keys_file": str(keys_file),
            "token_file": str(tmp_path / "token.json"),
        }),
        args=None,
        env=None,
        transport="stdio",
        command="cmd",
        url=None,
    )


def _oauth_callback_endpoint():
    mcp_routes.setup_mcp_routes(MagicMock())
    for route in mcp_routes.router.routes:
        if route.path.endswith("/oauth/callback"):
            return route.endpoint
    raise AssertionError("oauth callback route not registered")


def _failing_client_factory(exc_type, constructed_kwargs):
    class FailingAsyncClient:
        def __init__(self, *args, **kwargs):
            constructed_kwargs.update(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, *args, **kwargs):
            raise exc_type("simulated network failure")

    return FailingAsyncClient


def _patch_route_deps(monkeypatch, tmp_path, client_cls):
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = _fake_server(tmp_path)
    monkeypatch.setattr(mcp_routes, "SessionLocal", MagicMock(return_value=db))
    monkeypatch.setattr(mcp_routes, "require_admin", lambda request: None)
    monkeypatch.setattr(mcp_routes.httpx, "AsyncClient", client_cls)


@pytest.mark.parametrize("exc_type", [
    httpx.ConnectTimeout,
    httpx.ConnectError,
    httpx.ReadTimeout,
])
async def test_token_exchange_network_failure_returns_4xx(tmp_path, monkeypatch, exc_type):
    """Network errors reaching Google must yield a graceful 400, not a 500."""
    client_cls = _failing_client_factory(exc_type, {})
    _patch_route_deps(monkeypatch, tmp_path, client_cls)

    endpoint = _oauth_callback_endpoint()
    resp = await endpoint(code="authcode", state="srv1", request=SimpleNamespace(headers={}))

    assert resp.status_code == 400
    assert b"Could not reach Google" in resp.body


async def test_token_exchange_client_uses_explicit_timeout(tmp_path, monkeypatch):
    """The token-exchange client must set an explicit timeout, not rely on the 5s default."""
    constructed_kwargs = {}
    client_cls = _failing_client_factory(httpx.ConnectTimeout, constructed_kwargs)
    _patch_route_deps(monkeypatch, tmp_path, client_cls)

    endpoint = _oauth_callback_endpoint()
    await endpoint(code="authcode", state="srv1", request=SimpleNamespace(headers={}))

    assert constructed_kwargs.get("timeout") is not None
