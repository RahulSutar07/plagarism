"""Unit and integration tests for operational health checks, Sentry PII scrubbing, and configuration."""
from pathlib import Path
from fastapi.testclient import TestClient

from app.main import app
from app.sentry import init_sentry, scrub_pii_from_sentry_event

client = TestClient(app)


def test_deep_health_check_endpoint():
    res = client.get("/health")
    assert res.status_code == 200
    data = res.json()

    assert data["status"] in ("ok", "degraded")
    assert "connected" in data["database"]
    assert data["worker_disk"] == "ok"
    assert "text purge" in data["retention_policy"]
    assert "engine_version" in data
    assert "timestamp" in data


def test_sentry_init_with_empty_dsn():
    # Should safely return False and not crash when DSN is empty
    initialized = init_sentry()
    assert initialized is False


def test_sentry_pii_scrubbing_request_data():
    sample_event = {
        "request": {
            "headers": {
                "authorization": "Bearer super-secret-token",
                "cookie": "session_id=12345",
                "content-type": "application/json",
            },
            "data": {
                "title": "Quantum Paper",
                "text": "Confidential unpublished thesis research text that must never be sent to Sentry.",
                "password": "SecretPassword123!",
            },
        },
        "user": {
            "email": "student@university.edu",
            "ip_address": "192.168.1.55",
        },
        "breadcrumbs": {
            "values": [
                {"category": "auth", "data": {"password": "PlaintextPassword"}},
                {"category": "scan", "data": {"raw_text": "Sample copied paragraph"}},
            ]
        },
        "exception": {
            "values": [
                {
                    "type": "ValueError",
                    "stacktrace": {
                        "frames": [
                            {
                                "filename": "extract.py",
                                "vars": {
                                    "raw_text": "Secret text inside local variable",
                                    "page_count": 12,
                                },
                            }
                        ]
                    },
                }
            ]
        },
    }

    scrubbed = scrub_pii_from_sentry_event(sample_event)

    # 1. Headers scrubbed
    headers = scrubbed["request"]["headers"]
    assert headers["authorization"] == "[SCRUBBED]"
    assert headers["cookie"] == "[SCRUBBED]"
    assert headers["content-type"] == "application/json"

    # 2. Request body data scrubbed
    data = scrubbed["request"]["data"]
    assert data["text"] == "[SCRUBBED_DOCUMENT_DATA]"
    assert data["password"] == "[SCRUBBED_DOCUMENT_DATA]"
    assert data["title"] == "Quantum Paper"

    # 3. User object scrubbed
    assert scrubbed["user"]["email"] == "[ANONYMIZED_USER]"
    assert scrubbed["user"]["ip_address"] == "0.0.0.0"

    # 4. Breadcrumbs scrubbed
    crumb_values = scrubbed["breadcrumbs"]["values"]
    assert crumb_values[0]["data"]["password"] == "[SCRUBBED]"
    assert crumb_values[1]["data"]["raw_text"] == "[SCRUBBED]"

    # 5. Stack trace variables scrubbed
    frame_vars = scrubbed["exception"]["values"][0]["stacktrace"]["frames"][0]["vars"]
    assert frame_vars["raw_text"] == "[SCRUBBED_TEXT_VARIABLE]"
    assert frame_vars["page_count"] == 12


def test_env_example_matches_config():
    env_example_path = Path(".env.example")
    assert env_example_path.exists()
    content = env_example_path.read_text(encoding="utf-8")

    expected_keys = [
        "PC_ENV",
        "PC_SITE_URL",
        "PC_REDIS_URL",
        "PC_DATABASE_URL",
        "PC_JWT_SECRET_KEY",
        "PC_SENTRY_DSN",
        "PC_MAX_FILE_MB",
        "PC_DAILY_CHECKS_PER_USER",
        "PC_JOB_TEXT_MAX_AGE_MINUTES",
    ]

    for key in expected_keys:
        assert key in content, f"Expected key '{key}' missing from .env.example"
