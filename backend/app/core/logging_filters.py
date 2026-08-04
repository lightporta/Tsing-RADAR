"""Redact bearer-style artifact tokens from application access logs."""

from __future__ import annotations

import logging
import re

_ARTIFACT_TOKEN_PATH = re.compile(
    r"(?P<prefix>/(?:api/artifacts/download|v1/attachments)/)[^?\s\"]+"
)
_SENSITIVE_QUERY_VALUE = re.compile(
    r"(?i)(?P<prefix>[?&](?:token|access_token|authorization|signature|"
    r"api_key|app_key|idempotency_key|idempotency-key)=)[^&\s\"]+"
)
_SENSITIVE_HEADER_VALUE = re.compile(
    r"(?i)(?P<prefix>\b(?:Authorization|X-(?:Student|Admin|CSRF)-Token|"
    r"Idempotency-Key)\s*[:=]\s*(?:Bearer\s+|Basic\s+)?)[^\s,;\"]+"
)
_BARE_BEARER_VALUE = re.compile(
    r"(?i)(?P<prefix>\bBearer\s+)[^\s,;\"]+"
)
_BASIC_AUTH_URL = re.compile(
    r"(?i)(?P<prefix>https?://[^/@:\s]+:)[^@\s/]+@"
)


def redact_artifact_token(value: str) -> str:
    redacted = _ARTIFACT_TOKEN_PATH.sub(r"\g<prefix>[REDACTED]", value)
    redacted = _SENSITIVE_QUERY_VALUE.sub(r"\g<prefix>[REDACTED]", redacted)
    redacted = _SENSITIVE_HEADER_VALUE.sub(r"\g<prefix>[REDACTED]", redacted)
    redacted = _BARE_BEARER_VALUE.sub(r"\g<prefix>[REDACTED]", redacted)
    return _BASIC_AUTH_URL.sub(r"\g<prefix>[REDACTED]@", redacted)


class ArtifactTokenRedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # Render once so URL-like objects in ``record.args`` (for example
        # ``httpx.URL``) cannot bypass string-only argument handling.
        rendered = record.getMessage()
        redacted_rendered = redact_artifact_token(rendered)
        if redacted_rendered != rendered:
            record.msg = redacted_rendered
            record.args = ()
            return True
        if isinstance(record.msg, str):
            record.msg = redact_artifact_token(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(
                redact_artifact_token(value)
                if isinstance(value, str)
                else value
                for value in record.args
            )
        elif isinstance(record.args, dict):
            record.args = {
                key: (
                    redact_artifact_token(value)
                    if isinstance(value, str)
                    else value
                )
                for key, value in record.args.items()
            }
        return True


def install_artifact_token_log_redaction() -> None:
    for logger_name in ("uvicorn.access", "httpx"):
        logger = logging.getLogger(logger_name)
        if not any(
            isinstance(existing, ArtifactTokenRedactionFilter)
            for existing in logger.filters
        ):
            logger.addFilter(ArtifactTokenRedactionFilter())
