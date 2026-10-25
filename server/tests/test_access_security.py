from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from app.api import admin_auth
from app.cors_config import cors_origins
from app.login_limits import LoginLimiter


def test_client_window_expires_and_other_clients_are_independent():
    now = [0.0]
    limiter = LoginLimiter(per_client=2, clock=lambda: now[0])
    assert limiter.retry_after("a") == 0
    assert limiter.retry_after("a") == 0
    assert limiter.retry_after("a") == 60
    assert limiter.retry_after("b") == 0
    now[0] = 59.5
    assert limiter.retry_after("a") == 1
    now[0] = 60
    assert limiter.retry_after("a") == 0


def test_global_limit_and_bounded_table_fail_closed():
    limiter = LoginLimiter(total=2)
    assert [limiter.retry_after(str(i)) == 0 for i in range(3)] == [True, True, False]
    now = [0.0]
    limiter = LoginLimiter(max_clients=2, clock=lambda: now[0])
    assert limiter.retry_after("a") == limiter.retry_after("b") == 0
    assert limiter.retry_after("c") == 60
    assert len(limiter._clients) == 2
    now[0] = 60
    assert limiter.retry_after("c") == 0
    assert len(limiter._clients) == 1


def test_concurrent_attempts_cannot_exceed_limit():
    limiter = LoginLimiter()
    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(limiter.retry_after, ["a"] * 100))
    assert results.count(0) == 10


def test_login_throttle_cannot_be_bypassed_with_forwarded_header(monkeypatch):
    monkeypatch.setattr(admin_auth, "login_limiter", LoginLimiter(per_client=2))
    monkeypatch.setattr(admin_auth, "admin_auth_configured", lambda: True)
    monkeypatch.setattr(admin_auth, "verify_admin_login", lambda *args: False)
    app = FastAPI()
    app.include_router(admin_auth.router)
    with TestClient(app) as client:
        responses = [client.post("/api/auth/login", json={"username": "u", "password": "bad"},
                                 headers={"X-Forwarded-For": f"192.0.2.{i}"}) for i in range(3)]
    assert [r.status_code for r in responses] == [401, 401, 429]
    assert 1 <= int(responses[-1].headers["retry-after"]) <= 60


def test_successful_login_also_consumes_attempt(monkeypatch):
    monkeypatch.setattr(admin_auth, "login_limiter", LoginLimiter(per_client=1))
    monkeypatch.setattr(admin_auth, "admin_auth_configured", lambda: True)
    monkeypatch.setattr(admin_auth, "verify_admin_login", lambda *args: True)
    monkeypatch.setattr(admin_auth, "create_admin_token", lambda *args: "test-token")
    app = FastAPI()
    app.include_router(admin_auth.router)
    with TestClient(app) as client:
        first = client.post("/api/auth/login", json={"username": "u", "password": "p"})
        second = client.post("/api/auth/login", json={"username": "u", "password": "p"})
    assert first.json()["access_token"] == "test-token"
    assert second.status_code == 429


@pytest.mark.parametrize("value", ["*", "https://*.example.com", "null", "ftp://example.com", "http://x/path", "http://u:p@x", "http://x?x=1", "http://x:99999", "http://x:"])
def test_cors_rejects_non_origins(value):
    with pytest.raises(ValueError):
        cors_origins(value)


def test_cors_explicit_origins_and_preflight():
    assert cors_origins("") == []
    origins = cors_origins("http://localhost:5173, http://127.0.0.1:5173,http://localhost:5173")
    assert origins == ["http://localhost:5173", "http://127.0.0.1:5173"]
    app = FastAPI()
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["POST"],
                       allow_headers=["Authorization", "Content-Type"])
    with TestClient(app) as client:
        for origin, expected in [(origins[0], 200), ("https://evil.example", 400)]:
            response = client.options("/api/auth/login", headers={"Origin": origin,
                "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "authorization,content-type"})
            assert response.status_code == expected
            assert response.headers.get("access-control-allow-origin") == (origin if expected == 200 else None)


def test_application_cors_wiring_and_operator_route_policy():
    import os
    from app.auth_admin import require_admin
    from app.main import app

    cors = next(middleware for middleware in app.user_middleware if middleware.cls is CORSMiddleware)
    assert cors.kwargs["allow_origins"] == cors_origins(os.getenv("CORS_ALLOWED_ORIGINS", ""))
    assert cors.kwargs["allow_credentials"] is False
    assert "Authorization" in cors.kwargs["allow_headers"]
    assert "POST" in cors.kwargs["allow_methods"]
    # Public operator printing remains intentional; administration stays guarded.
    from app.api import cart, print as print_api, printers
    routes = {(route.path, method): route
              for router in (cart.router, print_api.router, printers.router)
              for route in router.routes
              for method in getattr(route, "methods", ())}
    for path in ("/api/cart", "/api/cart/print", "/api/print"):
        assert not any(dep.call is require_admin for dep in routes[(path, "POST")].dependant.dependencies)
    assert any(dep.call is require_admin for dep in routes[("/api/printers", "POST")].dependant.dependencies)


def test_application_cross_origin_integration_headers_and_retry_after(monkeypatch):
    import runpy
    from pathlib import Path

    origin = "http://localhost:5173"
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", origin)
    monkeypatch.setattr(admin_auth, "login_limiter", LoginLimiter(per_client=1))
    monkeypatch.setattr(admin_auth, "admin_auth_configured", lambda: True)
    monkeypatch.setattr(admin_auth, "verify_admin_login", lambda *args: False)
    # Execute real application setup in a fresh namespace so other tests retain
    # their existing app instance and middleware stack.
    main_path = Path(__file__).resolve().parents[1] / "app" / "main.py"
    app = runpy.run_path(str(main_path), run_name="app._cors_test")["app"]
    with TestClient(app) as client:
        response = client.options("/api/integrations/print", headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "idempotency-key,x-api-key,content-type",
        })
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == origin
        for header in ("idempotency-key", "x-api-key"):
            assert header in response.headers["access-control-allow-headers"].lower()
        responses = [client.post("/api/auth/login", headers={"Origin": origin},
                                json={"username": "u", "password": "bad"}) for _ in range(2)]
    assert [response.status_code for response in responses] == [401, 429]
    limited = responses[-1]
    assert limited.headers["access-control-allow-origin"] == origin
    assert "retry-after" in limited.headers["access-control-expose-headers"].lower()
    assert 1 <= int(limited.headers["retry-after"]) <= 60
