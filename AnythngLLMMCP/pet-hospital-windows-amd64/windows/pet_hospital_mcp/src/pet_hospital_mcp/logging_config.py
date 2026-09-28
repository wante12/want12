"""JSON logging with recursive sensitive-field redaction."""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any, Mapping

_SENSITIVE_KEYS = {"ownerphone", "owneraddr", "chipno"}


def _normalise_key(key: object) -> str:
    return "".join(character for character in str(key).lower() if character.isalnum())


def redact_sensitive(value: Any) -> Any:
    """Recursively replace sensitive values while preserving data shape."""

    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if _normalise_key(key) in _SENSITIVE_KEYS:
                result[str(key)] = "[REDACTED]"
            else:
                result[str(key)] = redact_sensitive(item)
        return result
    if isinstance(value, (list, tuple, set)):
        return [redact_sensitive(item) for item in value]
    return value


class JsonFormatter(logging.Formatter):
    """Render records as one JSON object per line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        event = getattr(record, "event", None)
        if isinstance(event, Mapping):
            payload.update(event)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(level: str = "INFO") -> None:
    """Install one JSON stderr handler without duplicating handlers on imports."""

    root = logging.getLogger()
    if not any(getattr(handler, "_pet_hospital_json", False) for handler in root.handlers):
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(JsonFormatter())
        handler._pet_hospital_json = True  # type: ignore[attr-defined]
        root.addHandler(handler)
    root.setLevel(level.upper())
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def log_tool_call(
    *,
    logger: logging.Logger,
    tool_name: str,
    params: Mapping[str, Any],
    status: str,
    duration_ms: float,
) -> None:
    logger.info(
        "tool call completed",
        extra={
            "event": {
                "tool_name": tool_name,
                "params": redact_sensitive(params),
                "status": status,
                "duration_ms": round(duration_ms, 2),
            }
        },
    )


