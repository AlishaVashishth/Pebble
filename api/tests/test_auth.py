"""Tests for authentication endpoints and security behaviors."""

import pytest
from fastapi import HTTPException, status
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from backend.app.core.exceptions import format_validation_error
from backend.app.db.base import Base
from backend.app.repositories.user_repository import UserRepository
from backend.app.schemas.auth import UserLoginRequest, UserRegisterRequest
from backend.app.services.auth_service import AuthService


@pytest.fixture
def sqlite_auth_session():
    """In-memory SQLite session for isolated auth unit tests."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(bind=engine)
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def test_auth_service_duplicate_email_409(sqlite_auth_session: Session):
    """Registering duplicate email raises 409 with exact detail message."""
    service = AuthService()
    req = UserRegisterRequest(name="Alice", email="alice@example.com", password="Password123!")
    service.register(sqlite_auth_session, req)

    with pytest.raises(HTTPException) as exc_info:
        service.register(sqlite_auth_session, req)
    assert exc_info.value.status_code == status.HTTP_409_CONFLICT
    assert exc_info.value.detail == "This email is already registered. Try logging in."


def test_auth_service_login_wrong_password_401(sqlite_auth_session: Session):
    """Wrong password raises 401 with uniform detail message."""
    service = AuthService()
    req = UserRegisterRequest(name="Bob", email="bob@example.com", password="CorrectPassword123!")
    service.register(sqlite_auth_session, req)

    with pytest.raises(HTTPException) as exc_info:
        service.login(sqlite_auth_session, UserLoginRequest(email="bob@example.com", password="WrongPassword999!"))
    assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert exc_info.value.detail == "Incorrect email or password."


def test_auth_service_login_unknown_email_401(sqlite_auth_session: Session):
    """Unknown email raises 401 with identical message to wrong password."""
    service = AuthService()
    with pytest.raises(HTTPException) as exc_info:
        service.login(sqlite_auth_session, UserLoginRequest(email="nobody@example.com", password="AnyPassword123!"))
    assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert exc_info.value.detail == "Incorrect email or password."


def test_format_validation_error_short_password():
    """Short password is formatted into a clean user-facing error message."""
    try:
        UserRegisterRequest(name="Charlie", email="charlie@example.com", password="short")
    except ValidationError as val_err:
        req_err = RequestValidationError(val_err.errors())
        formatted = format_validation_error(req_err)
        assert formatted == "Password must be at least 8 characters."


def test_format_validation_error_invalid_email():
    """Invalid email is formatted into a clean user-facing error message."""
    try:
        UserRegisterRequest(name="Charlie", email="notanemail", password="ValidPassword123!")
    except ValidationError as val_err:
        req_err = RequestValidationError(val_err.errors())
        formatted = format_validation_error(req_err)
        assert formatted == "Please enter a valid email address."


@pytest.mark.db
def test_register_ok(client, db_session: Session):
    """Register ok: returns 201, safe user object, and stores Argon2 password hash."""
    plain_password = "SecurePassword123!"
    payload = {
        "name": "Jane Doe",
        "email": "  Jane.Doe@Example.COM  ",
        "password": plain_password,
    }
    response = client.post("/auth/register", json=payload)
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    assert data["name"] == "Jane Doe"
    assert data["email"] == "jane.doe@example.com"
    assert data["onboarding_completed"] is False
    assert "id" in data
    assert "password_hash" not in data

    # Verify stored password hash in DB starts with $argon2 and is not plaintext
    user = UserRepository.get_by_email(db_session, "jane.doe@example.com")
    assert user is not None
    assert user.password_hash is not None
    assert user.password_hash.startswith("$argon2")
    assert user.password_hash != plain_password


@pytest.mark.db
def test_register_duplicate_email_409(client):
    """Duplicate email registration returns 409 Conflict."""
    payload = {
        "name": "Alice Smith",
        "email": "alice.duplicate@example.com",
        "password": "Password123!",
    }
    resp1 = client.post("/auth/register", json=payload)
    assert resp1.status_code == status.HTTP_201_CREATED

    resp2 = client.post("/auth/register", json=payload)
    assert resp2.status_code == status.HTTP_409_CONFLICT
    assert "already registered" in resp2.json().get("detail", "").lower() or "already registered" in resp2.text.lower()


@pytest.mark.db
def test_register_weak_password_422(client):
    """Password shorter than 8 characters returns 422 Unprocessable Entity."""
    response = client.post(
        "/auth/register",
        json={
            "name": "Weak Pass User",
            "email": "weak@example.com",
            "password": "short",
        },
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


@pytest.mark.db
def test_login_wrong_password_and_unknown_email_same_message(client):
    """Wrong password returns 401; unknown email gives the SAME message as wrong password."""
    email = "registered.user@example.com"
    client.post(
        "/auth/register",
        json={
            "name": "Registered User",
            "email": email,
            "password": "CorrectPassword123!",
        },
    )

    # Wrong password attempt
    wrong_pw_resp = client.post(
        "/auth/login",
        json={"email": email, "password": "WrongPassword999!"},
    )
    assert wrong_pw_resp.status_code == status.HTTP_401_UNAUTHORIZED
    wrong_pw_msg = wrong_pw_resp.json().get("message") or wrong_pw_resp.json().get("detail")

    # Unknown email attempt
    unknown_email_resp = client.post(
        "/auth/login",
        json={"email": "nonexistent.user@example.com", "password": "AnyPassword123!"},
    )
    assert unknown_email_resp.status_code == status.HTTP_401_UNAUTHORIZED
    unknown_email_msg = unknown_email_resp.json().get("message") or unknown_email_resp.json().get("detail")

    # Ensure both return the identical error message to avoid enumeration
    assert wrong_pw_msg == unknown_email_msg
    assert "incorrect email or password" in wrong_pw_msg.lower()


@pytest.mark.db
@pytest.mark.db
def test_login_rate_limit_429(client):
    """Login rate limit returns 429 after 5 attempts per minute."""
    payload = {"email": "rate.limit@example.com", "password": "WrongPassword123!"}
    for _ in range(5):
        resp = client.post("/auth/login", json=payload)
        assert resp.status_code == status.HTTP_401_UNAUTHORIZED

    # 6th attempt should be blocked with 429 Too Many Requests
    blocked_resp = client.post("/auth/login", json=payload)
    assert blocked_resp.status_code == status.HTTP_429_TOO_MANY_REQUESTS


@pytest.mark.db
def test_auth_no_token_401(client):
    """Accessing protected endpoint without a token returns 401 Unauthorized."""
    resp = client.get("/users/me")
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.db
def test_auth_garbage_token_401(client):
    """Accessing protected endpoint with garbage token returns 401 Unauthorized."""
    resp = client.get("/users/me", headers={"Authorization": "Bearer not.a.valid.jwt.token"})
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED
