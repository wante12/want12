from __future__ import annotations

import json

import httpx
import pytest

from pet_hospital_mcp.config import AppSettings
from pet_hospital_mcp.errors import ErrorCode, PetHospitalError
from pet_hospital_mcp.rest_client import PetHospitalRestClient
from pet_hospital_mcp.tools.list_pets import ListPetsInput


def settings(**overrides: object) -> AppSettings:
    values = {
        "base_url": "http://backend.test",
        "max_attempts": 1,
        "retry_backoff_seconds": 0,
    }
    values.update(overrides)
    return AppSettings(**values)  # type: ignore[arg-type]


async def test_success_parses_null_and_array_records_charges() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/pets"
        return httpx.Response(
            200,
            json={
                "code": 200,
                "message": "ok",
                "data": {
                    "items": [
                        {
                            "id": "PET-1",
                            "name": "旺财",
                            "species": "犬",
                            "records": None,
                            "charges": [{"id": "CH-1", "amount": 10.5}],
                            "totalCost": 10.5,
                            "visitCount": 0,
                        },
                        {
                            "id": "PET-2",
                            "name": "咪咪",
                            "species": "猫",
                            "records": [{"id": "MR-1"}],
                            "charges": None,
                            "totalCost": 0,
                            "visitCount": 1,
                        },
                    ],
                    "total": 2,
                    "page": 1,
                    "pageSize": 20,
                    "totalPages": 1,
                    "totalCost": 10.5,
                },
                "time": "2026-01-01T00:00:00+08:00",
            },
        )

    async with PetHospitalRestClient(settings(), transport=httpx.MockTransport(handler)) as client:
        output = await client.list_pets(ListPetsInput(page=1, pageSize=20))
    assert output.total == 2
    assert output.items[0].records is None
    assert output.items[0].charges == [{"id": "CH-1", "amount": 10.5}]
    assert output.items[1].charges is None
    assert output.items[1].records == [{"id": "MR-1"}]


async def test_backend_5xx_retries_then_returns_api_error() -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503, json={"code": 503, "message": "busy"})

    client = PetHospitalRestClient(
        settings(max_attempts=3),
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(PetHospitalError) as exc_info:
        await client.list_pets(ListPetsInput())
    await client.aclose()
    assert calls == 3
    assert exc_info.value.code is ErrorCode.BACKEND_API_ERROR
    assert exc_info.value.details["status"] == 503


async def test_backend_4xx_does_not_retry() -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(400, json={"code": 400, "message": "bad request"})

    client = PetHospitalRestClient(
        settings(max_attempts=3),
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(PetHospitalError) as exc_info:
        await client.list_pets(ListPetsInput())
    await client.aclose()
    assert calls == 1
    assert exc_info.value.code is ErrorCode.BACKEND_API_ERROR
    assert exc_info.value.details["status"] == 400


async def test_timeout_retries_and_returns_structured_timeout() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.TimeoutException("timed out", request=request)

    client = PetHospitalRestClient(
        settings(max_attempts=2),
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(PetHospitalError) as exc_info:
        await client.list_pets(ListPetsInput())
    await client.aclose()
    assert calls == 2
    assert exc_info.value.code is ErrorCode.BACKEND_TIMEOUT
    assert exc_info.value.details == {"attempts": 2}


async def test_connection_error_returns_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    async with PetHospitalRestClient(settings(), transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(PetHospitalError) as exc_info:
            await client.list_pets(ListPetsInput())
    assert exc_info.value.code is ErrorCode.BACKEND_UNAVAILABLE


async def test_invalid_json_returns_invalid_response() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not-json", headers={"content-type": "application/json"})

    async with PetHospitalRestClient(settings(), transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(PetHospitalError) as exc_info:
            await client.list_pets(ListPetsInput())
    assert exc_info.value.code is ErrorCode.BACKEND_INVALID_RESPONSE


async def test_response_model_mismatch_returns_invalid_response() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=json.dumps({"code": 200, "message": "ok", "data": {"items": []}}),
            headers={"content-type": "application/json"},
        )

    async with PetHospitalRestClient(settings(), transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(PetHospitalError) as exc_info:
            await client.list_pets(ListPetsInput())
    assert exc_info.value.code is ErrorCode.BACKEND_INVALID_RESPONSE
    assert "fields" in exc_info.value.details


async def test_success_envelope_with_non_200_code_is_api_error() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "code": 500,
                "message": "internal",
                "data": {
                    "items": [],
                    "total": 0,
                    "page": 1,
                    "pageSize": 20,
                    "totalPages": 0,
                    "totalCost": 0,
                },
            },
        )

    async with PetHospitalRestClient(settings(), transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(PetHospitalError) as exc_info:
            await client.list_pets(ListPetsInput())
    assert exc_info.value.code is ErrorCode.BACKEND_API_ERROR
    assert exc_info.value.details["code"] == 500
