from __future__ import annotations

import math

import httpx
import pytest
from pydantic import ValidationError

from pet_hospital_mcp.config import AppSettings
from pet_hospital_mcp.logging_config import redact_sensitive
from pet_hospital_mcp.rest_client import PetHospitalRestClient
from pet_hospital_mcp.server import create_server
from pet_hospital_mcp.tools.list_pets import ListPetsInput


def test_settings_defaults_and_environment() -> None:
    settings = AppSettings.from_env({})
    assert settings.host == "127.0.0.1"
    assert settings.port == 8000
    assert settings.base_url == "http://127.0.0.1:8080"

    configured = AppSettings.from_env(
        {
            "MCP_HOST": "localhost",
            "MCP_PORT": "9000",
            "PET_HOSPITAL_BASE_URL": "http://127.0.0.1:9090/",
        }
    )
    assert configured.host == "localhost"
    assert configured.port == 9000
    assert configured.base_url == "http://127.0.0.1:9090"


@pytest.mark.parametrize(
    ("environ", "message"),
    [
        ({"MCP_PORT": "0"}, "MCP_PORT"),
        ({"MCP_PORT": "abc"}, "MCP_PORT"),
        ({"PET_HOSPITAL_BASE_URL": "localhost:8080"}, "PET_HOSPITAL_BASE_URL"),
        ({"PET_HOSPITAL_MAX_ATTEMPTS": "0"}, "PET_HOSPITAL_MAX_ATTEMPTS"),
        ({"PET_HOSPITAL_TIMEOUT_SECONDS": "nan"}, "PET_HOSPITAL_TIMEOUT_SECONDS"),
    ],
)
def test_settings_reject_invalid_environment(environ: dict[str, str], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        AppSettings.from_env(environ)


def test_input_model_accepts_all_supported_fields() -> None:
    model = ListPetsInput.model_validate(
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
            "page": 2,
            "pageSize": 50,
        }
    )
    assert model.model_dump(exclude_none=True) == {
        "q": "旺财",
        "name": "旺财",
        "ownerName": "张三",
        "ownerPhone": "13800001111",
        "species": "犬",
        "doctor": "李医生",
        "disease": "肠胃炎",
        "status": "待就诊",
        "min": 100.0,
        "max": 1000.0,
        "sortBy": "totalCost",
        "order": "desc",
        "page": 2,
        "pageSize": 50,
    }


@pytest.mark.parametrize(
    "payload",
    [
        {"species": "马"},
        {"status": "未知"},
        {"sortBy": "unknown"},
        {"order": "up"},
        {"page": 0},
        {"pageSize": 501},
        {"min": -1},
        {"min": 20, "max": 10},
        {"page": "1"},
        {"extra": "not-allowed"},
        {"min": math.nan},
        {"min": math.inf},
    ],
)
def test_input_model_rejects_invalid_values(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        ListPetsInput.model_validate(payload)


async def test_tool_registration_name_schema_and_output_schema() -> None:
    settings = AppSettings(base_url="http://127.0.0.1:8080", max_attempts=1, retry_backoff_seconds=0)
    rest_client = PetHospitalRestClient(settings, transport=httpx.MockTransport(lambda _: httpx.Response(500)))
    server = create_server(settings, rest_client=rest_client)
    try:
        tools = await server.list_tools()
        assert [tool.name for tool in tools] == ["list_pets"]
        tool = tools[0]
        assert tool.input_schema["type"] == "object"
        assert tool.input_schema["additionalProperties"] is False
        assert set(tool.input_schema["properties"]) == {
            "q",
            "name",
            "ownerName",
            "ownerPhone",
            "species",
            "doctor",
            "disease",
            "status",
            "min",
            "max",
            "sortBy",
            "order",
            "page",
            "pageSize",
        }
        assert tool.input_schema["properties"]["species"]["anyOf"][0]["enum"] == [
            "犬",
            "猫",
            "兔",
            "鸟",
            "仓鼠",
            "爬宠",
            "其他",
        ]
        assert tool.input_schema["properties"]["page"]["minimum"] == 1
        assert tool.input_schema["properties"]["pageSize"]["maximum"] == 500
        assert tool.output_schema is None
    finally:
        await rest_client.aclose()




def test_sensitive_fields_are_redacted_recursively() -> None:
    payload = {
        "ownerPhone": "13800001111",
        "owner_phone": "13900001111",
        "ownerAddr": "北京市",
        "owner_addr": "上海市",
        "chipNo": "CHIP-1",
        "chip_no": "CHIP-2",
        "nested": [{"ownerPhone": "13700001111", "name": "旺财"}],
    }
    redacted = redact_sensitive(payload)
    assert redacted["ownerPhone"] == "[REDACTED]"
    assert redacted["owner_phone"] == "[REDACTED]"
    assert redacted["ownerAddr"] == "[REDACTED]"
    assert redacted["owner_addr"] == "[REDACTED]"
    assert redacted["chipNo"] == "[REDACTED]"
    assert redacted["chip_no"] == "[REDACTED]"
    assert redacted["nested"][0]["ownerPhone"] == "[REDACTED]"
    assert redacted["nested"][0]["name"] == "旺财"
