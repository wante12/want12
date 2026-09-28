"""Environment-backed configuration for the MCP service."""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlsplit


@dataclass(frozen=True, slots=True)
class AppSettings:
    """Runtime settings loaded from environment variables."""

    host: str = "127.0.0.1"
    port: int = 8000
    base_url: str = "http://127.0.0.1:8080"
    request_timeout_seconds: float = 5.0
    max_attempts: int = 3
    retry_backoff_seconds: float = 0.1
    log_level: str = "INFO"

    @classmethod
    def from_env(cls, environ: dict[str, str] | None = None) -> "AppSettings":
        env = os.environ if environ is None else environ
        host = env.get("MCP_HOST", "127.0.0.1").strip() or "127.0.0.1"
        port = _parse_int(env.get("MCP_PORT", "8000"), "MCP_PORT", minimum=1, maximum=65535)
        base_url = env.get("PET_HOSPITAL_BASE_URL", "http://127.0.0.1:8080").strip().rstrip("/")
        _validate_base_url(base_url)

        timeout = _parse_float(
            env.get("PET_HOSPITAL_TIMEOUT_SECONDS", "5"),
            "PET_HOSPITAL_TIMEOUT_SECONDS",
            minimum=0.01,
        )
        max_attempts = _parse_int(
            env.get("PET_HOSPITAL_MAX_ATTEMPTS", "3"),
            "PET_HOSPITAL_MAX_ATTEMPTS",
            minimum=1,
            maximum=10,
        )
        retry_backoff = _parse_float(
            env.get("PET_HOSPITAL_RETRY_BACKOFF_SECONDS", "0.1"),
            "PET_HOSPITAL_RETRY_BACKOFF_SECONDS",
            minimum=0.0,
        )
        log_level = env.get("MCP_LOG_LEVEL", "INFO").strip().upper() or "INFO"
        if log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError("MCP_LOG_LEVEL must be DEBUG, INFO, WARNING, ERROR, or CRITICAL")

        return cls(
            host=host,
            port=port,
            base_url=base_url,
            request_timeout_seconds=timeout,
            max_attempts=max_attempts,
            retry_backoff_seconds=retry_backoff,
            log_level=log_level,
        )


def _parse_int(raw: str, name: str, *, minimum: int, maximum: int) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def _parse_float(raw: str, name: str, *, minimum: float) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a number") from exc
    if value != value or value in {float("inf"), float("-inf")}:
        raise ValueError(f"{name} must be finite")
    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return value


def _validate_base_url(base_url: str) -> None:
    parsed = urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("PET_HOSPITAL_BASE_URL must be an absolute http:// or https:// URL")
