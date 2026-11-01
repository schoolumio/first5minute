"""Authentication flows through the HTTP API."""

import re

from app.services.email import OUTBOX
from tests.conftest import PASSWORD, login


def _register(client, email="new@example.com", password=PASSWORD):
    return client.post("/api/v1/auth/register", json={
        "email": email, "password": password, "full_name": "New", "country": "ng", "accept_terms": True, "confirm_age": True})


def _token_from_outbox(kind: str) -> str:
    mail = next(m for m in reversed(OUTBOX) if kind in m.body)
    return re.search(r"token=([\w-]+)", mail.body).group(1)


def test_register_verify_login_me(client):
    r = _register(client)
    assert r.status_code == 201
    assert _register(client).status_code == 409
    token = _token_from_outbox("verify-email")
    login(client, "new@example.com")
    me = client.get("/api/v1/auth/me").json()
    assert me["email"] == "new@example.com" and me["email_verified"] is False and me["country"] == "NG"
    assert me["entitlements"]["plan"] == "free"
    # Unverified users cannot use the scanner.
    assert client.get("/api/v1/scanner").status_code == 403
    assert client.post("/api/v1/auth/verify-email", json={"token": token}).status_code == 200
    assert client.post("/api/v1/auth/verify-email", json={"token": token}).status_code == 400  # single use
    assert client.get("/api/v1/auth/me").json()["email_verified"] is True


def test_registration_validation(client):
    assert _register(client, password="short").status_code == 422
    assert _register(client, password="alllowercase123").status_code == 422
    r = client.post("/api/v1/auth/register", json={"email": "a@example.com", "password": PASSWORD,
                                                   "accept_terms": True, "confirm_age": False})
    assert r.status_code == 422


def test_login_failure_and_lockout(client, user_factory):
    user_factory(email="lock@example.com")
    for _ in range(5):
        assert client.post("/api/v1/auth/login", json={"email": "lock@example.com", "password": "Wrong1Password"}).status_code == 401
    r = client.post("/api/v1/auth/login", json={"email": "lock@example.com", "password": PASSWORD})
    assert r.status_code == 429


def test_cookie_session_requires_csrf_for_mutations(client, user_factory):
    user_factory(email="csrf@example.com")
    login(client, "csrf@example.com")
    client.headers.pop("X-CSRF-Token")
    r = client.patch("/api/v1/account/profile", json={"full_name": "X"})
    assert r.status_code == 403 and "CSRF" in r.text
    client.headers["X-CSRF-Token"] = client.cookies.get("pf_csrf")
    assert client.patch("/api/v1/account/profile", json={"full_name": "X"}).status_code == 200


def test_bearer_token_works_without_csrf(client, user_factory):
    user_factory(email="api@example.com")
    token = client.post("/api/v1/auth/login", json={"email": "api@example.com", "password": PASSWORD}).json()["access_token"]
    client.cookies.clear()
    r = client.patch("/api/v1/account/profile", json={"full_name": "API"}, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert client.get("/api/v1/auth/me", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_refresh_rotation_and_reuse_detection(client, user_factory):
    user_factory(email="rot@example.com")
    login(client, "rot@example.com")
    first = client.cookies.get("pf_refresh")
    assert client.post("/api/v1/auth/refresh").status_code == 200
    assert client.cookies.get("pf_refresh") != first
    assert client.cookies.get("pf_csrf") == client.headers["X-CSRF-Token"]  # CSRF token stable across refresh
    # Replaying the consumed token revokes every session.
    client.cookies.set("pf_refresh", first, path="/api/v1/auth")
    assert client.post("/api/v1/auth/refresh").status_code == 401


def test_logout_revokes_refresh(client, user_factory):
    user_factory(email="out@example.com")
    login(client, "out@example.com")
    refresh, csrf = client.cookies.get("pf_refresh"), client.cookies.get("pf_csrf")
    assert client.post("/api/v1/auth/logout").status_code == 200
    assert client.cookies.get("pf_refresh") is None
    client.cookies.set("pf_refresh", refresh, path="/api/v1/auth")
    client.cookies.set("pf_csrf", csrf, path="/")
    assert client.post("/api/v1/auth/refresh").status_code == 401


def test_forgot_and_reset_password(client, user_factory):
    user_factory(email="reset@example.com")
    assert client.post("/api/v1/auth/forgot-password", json={"email": "missing@example.com"}).status_code == 200
    assert not OUTBOX
    assert client.post("/api/v1/auth/forgot-password", json={"email": "reset@example.com"}).status_code == 200
    token = _token_from_outbox("reset-password")
    new = "AnotherGood1Pass"
    assert client.post("/api/v1/auth/reset-password", json={"token": token, "password": new}).status_code == 200
    assert client.post("/api/v1/auth/reset-password", json={"token": token, "password": new}).status_code == 400
    assert client.post("/api/v1/auth/login", json={"email": "reset@example.com", "password": PASSWORD}).status_code == 401
    login(client, "reset@example.com", new)


def test_auth_rate_limit(client, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "rate_limit_enabled", True)
    monkeypatch.setattr(get_settings(), "rate_limit_auth_per_minute", 3)
    codes = [client.post("/api/v1/auth/forgot-password", json={"email": "x@example.com"}).status_code for _ in range(5)]
    assert codes[:3] == [200, 200, 200] and codes[-1] == 429


def test_login_accepts_existing_account_with_reserved_tld(client, user_factory):
    # Regression: strict email syntax on login locked out accounts created by the CLI.
    user_factory(email="admin@projectfive.local", role="admin")
    login(client, "admin@projectfive.local")
