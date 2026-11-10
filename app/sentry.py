"""Sentry error monitoring integration with mandatory PII and document text scrubbing.

Ensures that error tracking never transmits user document content, raw text,
file attachments, or authentication credentials to external monitoring servers.
"""
from __future__ import annotations

import logging
from typing import Any

from app.config import get_settings

logger = logging.getLogger(__name__)

SENSITIVE_KEYS = {
    "text",
    "raw_text",
    "password",
    "content",
    "file",
    "token",
    "access_token",
    "authorization",
    "secret",
}


def scrub_pii_from_sentry_event(event: dict[str, Any], hint: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Filter hook executed before any event is sent to Sentry.
    
    Scrubs:
    1. Request payload data (removing document text and passwords).
    2. Header tokens (Authorization, Cookie).
    3. User PII (email, plain IP addresses).
    4. Breadcrumb payloads.
    5. Local variables in exception stack traces.
    """
    # 1. Scrub request data
    request = event.get("request")
    if isinstance(request, dict):
        # Scrub headers
        headers = request.get("headers")
        if isinstance(headers, dict):
            for h in ["authorization", "cookie", "x-forwarded-for"]:
                if h in headers:
                    headers[h] = "[SCRUBBED]"

        # Scrub request body
        data = request.get("data")
        if isinstance(data, dict):
            for k in list(data.keys()):
                if any(s in k.lower() for s in SENSITIVE_KEYS):
                    data[k] = "[SCRUBBED_DOCUMENT_DATA]"
        elif isinstance(data, str) and len(data) > 30:
            request["data"] = "[SCRUBBED_RAW_BODY]"

    # 2. Scrub user object
    user = event.get("user")
    if isinstance(user, dict):
        if "email" in user:
            user["email"] = "[ANONYMIZED_USER]"
        if "ip_address" in user:
            user["ip_address"] = "0.0.0.0"

    # 3. Scrub breadcrumbs
    breadcrumbs = event.get("breadcrumbs")
    if isinstance(breadcrumbs, dict) and "values" in breadcrumbs:
        for b in breadcrumbs["values"]:
            b_data = b.get("data")
            if isinstance(b_data, dict):
                for k in list(b_data.keys()):
                    if any(s in k.lower() for s in SENSITIVE_KEYS):
                        b_data[k] = "[SCRUBBED]"

    # 4. Scrub stack trace local variables
    exception = event.get("exception")
    if isinstance(exception, dict) and "values" in exception:
        for val in exception["values"]:
            stack = val.get("stacktrace")
            if isinstance(stack, dict) and "frames" in stack:
                for frame in stack["frames"]:
                    vars_dict = frame.get("vars")
                    if isinstance(vars_dict, dict):
                        for var_name in list(vars_dict.keys()):
                            if any(s in var_name.lower() for s in SENSITIVE_KEYS):
                                vars_dict[var_name] = "[SCRUBBED_TEXT_VARIABLE]"

    return event


def init_sentry() -> bool:
    """Initialize Sentry error reporting if DSN is configured."""
    settings = get_settings()
    if not settings.sentry_dsn:
        logger.info("Sentry monitoring disabled (PC_SENTRY_DSN not set).")
        return False

    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            environment=settings.env,
            release=f"plagiarism-checker@{settings.engine_version}",
            before_send=scrub_pii_from_sentry_event,
            send_default_pii=False,
            integrations=[
                FastApiIntegration(transaction_style="endpoint"),
                SqlalchemyIntegration(),
            ],
            traces_sample_rate=0.1 if settings.env == "prod" else 1.0,
        )
        logger.info("Sentry monitoring initialized with strict PII scrubbing.")
        return True
    except Exception as e:
        logger.warning("Failed to initialize Sentry: %s", e)
        return False
