"""HTTP client for the existing Go Pet Hospital REST API."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

from pet_hospital_mcp.config import AppSettings
from pet_hospital_mcp.errors import ErrorCode, PetHospitalError, validation_details

logger = logging.getLogger(__name__)


class Pet(BaseModel):
    """A pet row from the backend list response.

    Unknown fields are retained so the MCP client receives the backend's real
    record shape. `records` and `charges` deliberately accept null and arrays.
    """

    model_config = ConfigDict(extra="allow")

    id: str
    name: str
    species: str | None = None
    breed: str | None = None
    gender: str | None = None
    ageMonths: int | None = None
    color: str | None = None
    chipNo: str | None = None
    ownerName: str | None = None
    ownerPhone: str | None = None
    ownerAddr: str | None = None
    doctor: str | None = None
    disease: str | None = None
    status: str | None = None
    allergy: str | None = None
    note: str | None = None
    records: list[dict[str, Any]] | None = None
    charges: list[dict[str, Any]] | None = None
    totalCost: float = 0.0
    visitCount: int = 0
    createdAt: str | None = None
    updatedAt: str | None = None


class ListPetsOutput(BaseModel):
    """The exact `data` payload returned by `GET /api/v1/pets`."""

    model_config = ConfigDict(extra="ignore")

    items: list[Pet]
    total: int
    page: int
    pageSize: int
    totalPages: int
    totalCost: float


class _ApiEnvelope(BaseModel):
    model_config = ConfigDict(extra="ignore")

    code: int
    message: str = ""
    data: ListPetsOutput
    time: str | None = None


class PetHospitalRestClient:
    """Small, retrying async client for the one supported backend endpoint."""

    def __init__(
        self,
        settings: AppSettings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=settings.base_url,
            timeout=settings.request_timeout_seconds,
            transport=transport,
        )

    async def __aenter__(self) -> "PetHospitalRestClient":
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def list_pets(self, filters: BaseModel) -> ListPetsOutput:
        params = filters.model_dump(mode="json", exclude_none=True)
        last_error: PetHospitalError | None = None

        for attempt in range(1, self._settings.max_attempts + 1):
            try:
                response = await self._client.get("/api/v1/pets", params=params)
            except httpx.TimeoutException as exc:
                last_error = PetHospitalError(
                    ErrorCode.BACKEND_TIMEOUT,
                    "The Pet Hospital API timed out.",
                    {"attempts": attempt},
                )
                logger.warning("Pet Hospital API timeout on attempt %s (%s)", attempt, type(exc).__name__)
            except httpx.RequestError as exc:
                last_error = PetHospitalError(
                    ErrorCode.BACKEND_UNAVAILABLE,
                    "The Pet Hospital API is unavailable.",
                    {"attempts": attempt},
                )
                logger.warning("Pet Hospital API connection failure on attempt %s (%s)", attempt, type(exc).__name__)
            else:
                if 500 <= response.status_code < 600 and attempt < self._settings.max_attempts:
                    logger.warning("Pet Hospital API returned %s; retrying", response.status_code)
                    last_error = _api_error(response, attempt)
                elif not 200 <= response.status_code < 300:
                    raise _api_error(response, attempt)
                else:
                    return self._parse_success(response)

            if attempt < self._settings.max_attempts:
                await asyncio.sleep(self._settings.retry_backoff_seconds * (2 ** (attempt - 1)))

        assert last_error is not None
        if last_error.details.get("status") is not None:
            raise last_error
        raise PetHospitalError(
            last_error.code,
            last_error.message,
            {**last_error.details, "attempts": self._settings.max_attempts},
        )

    @staticmethod
    def _parse_success(response: httpx.Response) -> ListPetsOutput:
        try:
            raw = response.json()
        except ValueError as exc:
            raise PetHospitalError(
                ErrorCode.BACKEND_INVALID_RESPONSE,
                "The Pet Hospital API returned invalid JSON.",
            ) from exc

        try:
            envelope = _ApiEnvelope.model_validate(raw)
        except ValidationError as exc:
            raise PetHospitalError(
                ErrorCode.BACKEND_INVALID_RESPONSE,
                "The Pet Hospital API response did not match the expected model.",
                validation_details(exc),
            ) from exc

        if envelope.code != 200:
            raise PetHospitalError(
                ErrorCode.BACKEND_API_ERROR,
                "The Pet Hospital API reported an error.",
                {"code": envelope.code, "backendMessage": envelope.message[:300]},
            )
        return envelope.data


def _api_error(response: httpx.Response, attempt: int) -> PetHospitalError:
    details: dict[str, Any] = {"status": response.status_code, "attempts": attempt}
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        message = payload.get("message") or payload.get("error")
        if isinstance(message, str) and message:
            details["backendMessage"] = message[:300]
    return PetHospitalError(
        ErrorCode.BACKEND_API_ERROR,
        f"The Pet Hospital API returned HTTP {response.status_code}.",
        details,
    )

