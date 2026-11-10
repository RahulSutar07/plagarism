"""Unit and regression tests for authentication rate limiting, EmailStr validation, and password policy."""
import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from starlette.datastructures import Headers
from starlette.requests import Request

from app.auth import UserLoginRequest, UserRegisterRequest, validate_password_strength
from app.database import SessionLocal
from app.main import login_user, register_user
from app.models import RateLimitRecord, User
from app.rate_limit import enforce_auth_rate_limit, get_client_ip


def make_mock_request(client_ip: str = "127.0.0.1", headers: dict | None = None) -> Request:
    raw_headers = []
    if headers:
        for k, v in headers.items():
            raw_headers.append((k.lower().encode("latin-1"), v.encode("latin-1")))
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/auth/login",
        "headers": raw_headers,
        "client": (client_ip, 12345),
    }
    return Request(scope)


def test_proxy_header_ip_resolution():
    # 1. Cloudflare header precedence
    req_cf = make_mock_request(
        "127.0.0.1",
        {"CF-Connecting-IP": "203.0.113.195", "X-Forwarded-For": "198.51.100.10, 10.0.0.1"},
    )
    assert get_client_ip(req_cf) == "203.0.113.195"

    # 2. X-Real-IP precedence over X-Forwarded-For
    req_real = make_mock_request(
        "127.0.0.1",
        {"X-Real-IP": "198.51.100.55", "X-Forwarded-For": "192.0.2.1, 10.0.0.1"},
    )
    assert get_client_ip(req_real) == "198.51.100.55"

    # 3. X-Forwarded-For first IP extraction
    req_xff = make_mock_request("127.0.0.1", {"X-Forwarded-For": "192.0.2.99, 10.0.0.2"})
    assert get_client_ip(req_xff) == "192.0.2.99"

    # 4. Fallback to direct client host
    req_direct = make_mock_request("198.51.100.77")
    assert get_client_ip(req_direct) == "198.51.100.77"


def test_password_policy_complexity_checks():
    # Less than 8 characters
    with pytest.raises(ValueError, match="at least 8 characters"):
        validate_password_strength("Short1!")

    # Missing uppercase
    with pytest.raises(ValueError, match="uppercase letter"):
        validate_password_strength("password123!")

    # Missing lowercase
    with pytest.raises(ValueError, match="lowercase letter"):
        validate_password_strength("PASSWORD123!")

    # Missing number
    with pytest.raises(ValueError, match="number"):
        validate_password_strength("PasswordOnly!")

    # Missing special character
    with pytest.raises(ValueError, match="special character"):
        validate_password_strength("Password123")

    # Valid compliant password
    validate_password_strength("SecureP@ssw0rd2026")


def test_emailstr_validation():
    # Valid emails
    valid_req = UserRegisterRequest(email="student@university.edu", password="ValidPassword123!")
    assert valid_req.email == "student@university.edu"

    valid_subdomain = UserRegisterRequest(email="user@sub.domain.co.in", password="ValidPassword123!")
    assert valid_subdomain.email == "user@sub.domain.co.in"

    # Invalid emails rejected by Pydantic EmailStr
    with pytest.raises(ValidationError):
        UserRegisterRequest(email="plainaddress", password="ValidPassword123!")

    with pytest.raises(ValidationError):
        UserRegisterRequest(email="@missingusername.com", password="ValidPassword123!")

    with pytest.raises(ValidationError):
        UserRegisterRequest(email="missingdomain@", password="ValidPassword123!")


def test_login_rate_limiting_per_ip_and_email(db_session=None):
    with SessionLocal() as db:
        test_ip = "198.51.100.88"
        test_email = "bruteforce_target@test.edu"

        # 1. Exhaust per-email limit (5 attempts within 900s)
        for i in range(5):
            enforce_auth_rate_limit(
                db,
                f"login:email:{test_email}",
                max_requests=5,
                window_seconds=900,
                action_name="login",
            )

        # 6th attempt should raise 429
        with pytest.raises(HTTPException) as exc_info:
            enforce_auth_rate_limit(
                db,
                f"login:email:{test_email}",
                max_requests=5,
                window_seconds=900,
                action_name="login",
            )
        assert exc_info.value.status_code == 429
        assert "Retry-After" in exc_info.value.headers
        assert "Too many login attempts" in exc_info.value.detail

        # 2. Exhaust per-IP limit (10 attempts within 900s)
        for i in range(10):
            enforce_auth_rate_limit(
                db,
                f"login:ip:{test_ip}",
                max_requests=10,
                window_seconds=900,
                action_name="login",
            )

        # 11th attempt should raise 429
        with pytest.raises(HTTPException) as exc_info_ip:
            enforce_auth_rate_limit(
                db,
                f"login:ip:{test_ip}",
                max_requests=10,
                window_seconds=900,
                action_name="login",
            )
        assert exc_info_ip.value.status_code == 429
        assert "Retry-After" in exc_info_ip.value.headers


def test_register_rate_limiting_per_ip(db_session=None):
    with SessionLocal() as db:
        reg_ip = "192.0.2.77"
        # 10 registrations per IP per hour
        for i in range(10):
            enforce_auth_rate_limit(
                db,
                f"register:ip:{reg_ip}",
                max_requests=10,
                window_seconds=3600,
                action_name="registration",
            )

        # 11th registration should raise 429
        with pytest.raises(HTTPException) as exc_info:
            enforce_auth_rate_limit(
                db,
                f"register:ip:{reg_ip}",
                max_requests=10,
                window_seconds=3600,
                action_name="registration",
            )
        assert exc_info.value.status_code == 429
        assert "Too many registration attempts" in exc_info.value.detail


def test_endpoint_register_and_login_validation_flow():
    import uuid
    with SessionLocal() as db:
        unique_email = f"student.{uuid.uuid4().hex[:8]}@university.ac.in"
        req = make_mock_request(client_ip="192.168.10.50")

        # 1. Weak password rejected by Pydantic schema validation
        with pytest.raises(ValidationError) as weak_pw_exc:
            UserRegisterRequest(email=unique_email, password="weakpassword")
        assert "uppercase" in str(weak_pw_exc.value)

        # 2. Valid strong registration succeeds
        token_res = register_user(
            request=req,
            payload=UserRegisterRequest(email=unique_email, password="StrongPassword123!"),
            db=db,
        )
        assert token_res.access_token is not None
        assert token_res.email == unique_email

        # 3. Valid login succeeds
        login_res = login_user(
            request=req,
            payload=UserLoginRequest(email=unique_email, password="StrongPassword123!"),
            db=db,
        )
        assert login_res.access_token is not None

        # 4. Wrong password login fails with 401
        with pytest.raises(HTTPException) as wrong_pw_exc:
            login_user(
                request=req,
                payload=UserLoginRequest(email=unique_email, password="WrongPassword99!"),
                db=db,
            )
        assert wrong_pw_exc.value.status_code == 401
