"""Unit and integration tests for authentication, password hashing, and JWT tokens."""
import uuid
from fastapi.testclient import TestClient

from app.auth import hash_password, verify_password
from app.main import app

client = TestClient(app)


def test_password_hashing_and_verification():
    pw = "SuperSecretPass123!"
    hashed = hash_password(pw)

    assert hashed != pw
    assert verify_password(pw, hashed) is True
    assert verify_password("WrongPassword123!", hashed) is False


def test_auth_registration_and_login_flow():
    email = f"scholar.{uuid.uuid4().hex[:8]}@university.edu"
    password = "AcademicPassword2026!"

    # 1. Register
    reg_res = client.post(
        "/api/auth/register",
        json={"email": email, "password": password},
    )
    assert reg_res.status_code == 201
    reg_data = reg_res.json()
    assert "access_token" in reg_data
    assert reg_data["email"] == email
    assert reg_data["tier"] == "free"
    token = reg_data["access_token"]

    # 2. Duplicate registration rejected
    dup_res = client.post(
        "/api/auth/register",
        json={"email": email, "password": password},
    )
    assert dup_res.status_code == 400
    assert "already exists" in dup_res.json()["detail"]

    # 3. Invalid email rejected
    bad_email_res = client.post(
        "/api/auth/register",
        json={"email": "not-an-email", "password": password},
    )
    assert bad_email_res.status_code == 400

    # 4. Login with correct password
    login_res = client.post(
        "/api/auth/login",
        json={"email": email, "password": password},
    )
    assert login_res.status_code == 200
    assert login_res.json()["access_token"] is not None

    # 5. Login with wrong password rejected
    bad_login_res = client.post(
        "/api/auth/login",
        json={"email": email, "password": "WrongPassword99!"},
    )
    assert bad_login_res.status_code == 401

    # 6. Profile query with Bearer token
    headers = {"Authorization": f"Bearer {token}"}
    me_res = client.get("/api/auth/me", headers=headers)
    assert me_res.status_code == 200
    me_data = me_res.json()
    assert me_data["email"] == email
    assert me_data["daily_quota"] == 5

    # 7. Profile query without token rejected
    unauth_res = client.get("/api/auth/me")
    assert unauth_res.status_code == 401
