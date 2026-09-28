from __future__ import annotations

import json
import math
from typing import Any

import httpx
import pytest

from conftest import call_tool, mcp_request, running_mcp_app
from pet_hospital_mcp.config import AppSettings


def app_settings(**overrides: Any) -> AppSettings:
    values = {
        "base_url": "http://backend.test",
        "max_attempts": 1,
        "retry_backoff_seconds": 0,
    }
    values.update(overrides)
    return AppSettings(**values)


def success_payload() -> dict[str, Any]:
    return {
        "code": 200,
        "message": "ok",
        "data": {
            "items": [
                {
                    "id": "PET-000001",
                    "name": "旺财",
                    "species": "犬",
                    "ownerName": "张三",
                    "ownerPhone": "13800001111",
                    "ownerAddr": "北京市",
                    "chipNo": "CHIP-1",
                    "doctor": "李医生",
                    "disease": "肠胃炎",
                    "status": "待就诊",
                    "records": None,
                    "charges": [],
                    "totalCost": 380,
                    "visitCount": 0,
                }
            ],
            "total": 1,
            "page": 1,
            "pageSize": 10,
            "totalPages": 1,
            "totalCost": 380,
        },
        "time": "2026-01-01T00:00:00+08:00",
    }


async def test_health_endpoint() -> None:
    seen: list[str] = []

    def backend(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(200, json=success_payload())

    async with running_mcp_app(app_settings(), backend) as (client, _, _):
        response = await client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "healthy"
    assert body["protocolVersion"] == "2026-07-28"
    assert body["sdk"] == "mcp==2.0.0"
    assert seen == []


async def test_modern_stateless_discovery_list_and_call() -> None:
    requests: list[httpx.Request] = []

    def backend(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=success_payload())

    async with running_mcp_app(app_settings(), backend) as (client, _, _):
        discover = await mcp_request(client, "server/discover", request_id=1)
        tools = await mcp_request(client, "tools/list", params={}, request_id=2)
        called = await call_tool(
            client,
            {
                "q": "旺财",
                "name": "旺财",
                "ownerName": "张三",
                "ownerPhone": "13800001111",
                "species": "犬",
                "doctor": "李医生",
                "disease": "肠胃炎",
                "status": "待就诊",
                "min": 100,
                "max": 1000,
                "sortBy": "totalCost",
                "order": "desc",
                "page": 1,
                "pageSize": 10,
            },
            request_id=3,
        )

    assert discover.status_code == 200
    assert tools.status_code == 200
    assert called.status_code == 200
    assert "mcp-session-id" not in discover.headers
    assert "mcp-session-id" not in tools.headers
    assert "mcp-session-id" not in called.headers

    discover_result = discover.json()["result"]
    assert "2026-07-28" in discover_result["supportedVersions"]
    assert "tools" in discover_result["capabilities"]

    listed = tools.json()["result"]["tools"]
    assert [tool["name"] for tool in listed] == ["list_pets"]
    assert listed[0]["inputSchema"]["additionalProperties"] is False

    call_result = called.json()["result"]
    assert call_result["isError"] is False
    assert call_result["structuredContent"]["total"] == 1
    assert call_result["structuredContent"]["items"][0]["records"] is None

    assert len(requests) == 1
    backend_request = requests[0]
    assert backend_request.url.path == "/api/v1/pets"
    assert dict(backend_request.url.params) == {
        "q": "旺财",
        "name": "旺财",
        "ownerName": "张三",
        "ownerPhone": "13800001111",
        "species": "犬",
        "doctor": "李医生",
        "disease": "肠胃炎",
        "status": "待就诊",
        "min": "100.0",
        "max": "1000.0",
        "sortBy": "totalCost",
        "order": "desc",
        "page": "1",
        "pageSize": "10",
    }


async def test_invalid_tool_argument_returns_unified_structured_error() -> None:
    backend_calls = 0

    def backend(_: httpx.Request) -> httpx.Response:
        nonlocal backend_calls
        backend_calls += 1
        return httpx.Response(200, json=success_payload())

    async with running_mcp_app(app_settings(), backend) as (client, _, _):
        response = await call_tool(client, {"species": "马"})

    assert response.status_code == 200
    result = response.json()["result"]
    assert result["isError"] is True
    assert result["structuredContent"] == {
        "error": {
            "code": "VALIDATION_ERROR",
            "message": "Invalid list_pets parameters.",
            "details": {
                "fields": [
                    {
                        "field": "species",
                        "reason": "Input should be '犬', '猫', '兔', '鸟', '仓鼠', '爬宠' or '其他'",
                    }
                ]
            },
        }
    }
    assert "马" not in result["content"][0]["text"]
    assert backend_calls == 0


async def test_unknown_field_returns_validation_error_before_sdk_ignores_it() -> None:
    async with running_mcp_app(app_settings(), lambda _: httpx.Response(200, json=success_payload())) as (
        client,
        _,
        _,
    ):
        response = await call_tool(client, {"page": 1, "unknown": "value"})
    result = response.json()["result"]
    assert result["isError"] is True
    assert result["structuredContent"]["error"]["code"] == "VALIDATION_ERROR"
    assert result["structuredContent"]["error"]["details"]["fields"][0]["field"] == "unknown"


async def test_backend_error_is_returned_as_structured_tool_error() -> None:
    def backend(_: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"code": 500, "message": "boom"})

    async with running_mcp_app(app_settings(), backend) as (client, _, _):
        response = await call_tool(client, {})
    result = response.json()["result"]
    assert result["isError"] is True
    assert result["structuredContent"]["error"]["code"] == "BACKEND_API_ERROR"
    assert result["structuredContent"]["error"]["details"]["status"] == 500
    assert "Traceback" not in result["content"][0]["text"]


async def test_invalid_backend_json_is_not_leaked() -> None:
    def backend(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"{bad json", headers={"content-type": "application/json"})

    async with running_mcp_app(app_settings(), backend) as (client, _, _):
        response = await call_tool(client, {})
    result = response.json()["result"]
    assert result["isError"] is True
    assert result["structuredContent"]["error"]["code"] == "BACKEND_INVALID_RESPONSE"
    assert "JSONDecodeError" not in result["content"][0]["text"]



@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
async def test_non_finite_numeric_values_return_structured_validation_error(value: float) -> None:
    async with running_mcp_app(app_settings(), lambda _: httpx.Response(200, json=success_payload())) as (
        client,
        _,
        _,
    ):
        body = {
            "jsonrpc": "2.0",
            "id": 9,
            "method": "tools/call",
            "params": {
                "name": "list_pets",
                "arguments": {"min": value},
                "_meta": {
                    "io.modelcontextprotocol/protocolVersion": "2026-07-28",
                    "io.modelcontextprotocol/clientCapabilities": {},
                },
            },
        }
        response = await client.post(
            "/mcp",
            content=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
                "Mcp-Protocol-Version": "2026-07-28",
                "Mcp-Method": "tools/call",
                "Mcp-Name": "list_pets",
            },
        )
    result = response.json()["result"]
    assert result["isError"] is True
    assert result["structuredContent"]["error"]["code"] == "VALIDATION_ERROR"
    assert result["structuredContent"]["error"]["details"]["fields"][0]["field"] == "min"
    assert "nan" not in result["content"][0]["text"].lower()
    assert "inf" not in result["content"][0]["text"].lower()

async def test_legacy_initialize_is_rejected_without_session_header() -> None:
    async with running_mcp_app(app_settings(), lambda _: httpx.Response(200, json=success_payload())) as (
        client,
        _,
        _,
    ):
        response = await client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            headers={
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
            },
        )
    assert "mcp-session-id" not in response.headers
    assert response.json()["error"]["message"] == "This server only accepts the stateless 2026-07-28 protocol."





