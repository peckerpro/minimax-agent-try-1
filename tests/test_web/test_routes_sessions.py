"""Regression tests for the FastAPI sessions routes.

These tests pin down the v0.2 web-UI sessions panel bug:
    `GET /api/sessions/` returning **500** with
    `AttributeError: 'generator' object does not support the context
    manager protocol`.

Root cause was `_open_episodic()` being a bare `yield`-generator
without the `@contextmanager` decorator — a plain generator does
NOT implement `__enter__`/`__exit__`, so `with _open_episodic() as em:`
raised on the very first request.

We exercise the route through `TestClient` (which runs the FastAPI
lifespan and the real SQLite-backed episodic store against a tmp
`$HELLO_AGENT_HOME` provided by the shared `app_client` fixture).
"""
from __future__ import annotations

from fastapi.testclient import TestClient


def test_list_sessions_returns_non_500(app_client: TestClient) -> None:
    """`GET /api/sessions/` must NOT 500.

    Pre-fix this raised
    `AttributeError: 'generator' object does not support the context manager protocol`
    inside `_open_episodic()`. Post-fix it returns a (possibly empty)
    JSON list with status 200.
    """
    r = app_client.get("/api/sessions/")
    assert r.status_code < 500, f"got {r.status_code}: {r.text}"
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_list_sessions_limit_validation(app_client: TestClient) -> None:
    """Out-of-range `limit` returns a clean 400, not a 500."""
    r = app_client.get("/api/sessions/?limit=0")
    assert r.status_code == 400
    r = app_client.get("/api/sessions/?limit=99999")
    assert r.status_code == 400


def test_get_session_unknown_id_returns_empty(app_client: TestClient) -> None:
    """`GET /api/sessions/{id}` for an unknown session returns 200 with empty messages.

    Pre-fix this would 500 with the generator/context-manager AttributeError.
    Post-fix the route happily returns an empty messages list.
    """
    r = app_client.get("/api/sessions/does-not-exist")
    assert r.status_code == 200
    body = r.json()
    assert body["session_id"] == "does-not-exist"
    assert body["messages"] == []


def test_resume_unknown_session_returns_404(app_client: TestClient) -> None:
    """`POST /api/sessions/{id}/resume` for an unknown session returns 404."""
    r = app_client.post("/api/sessions/does-not-exist/resume")
    assert r.status_code == 404