"""MCP 客户端测试。

大部分测试离线：用假的 Manager / 假的路由验证包装、命名冲突、错误处理。
另有一组「真实连接」测试，仅在本地 MCP Server 可连时才运行。
"""

from __future__ import annotations

import json
import socket
import sys
from pathlib import Path
from typing import Any

import pytest

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from core.mcp import (  # noqa: E402
    McpCallResult,
    McpConfigError,
    McpManager,
    McpServerStatus,
    McpToolInfo,
    McpToolRoute,
    McpToolWrapper,
    build_mcp_prompt,
    build_mcp_tools,
    load_mcp_config,
)
from core.mcp.client import _to_call_result  # noqa: E402
from core.mcp.manager import _sanitize  # noqa: E402
from core.tools.base import ToolRegistry  # noqa: E402


# ---------------------------------------------------------------- .mcp.json
def write_config(root: Path, servers: dict[str, Any]) -> Path:
    path = root / ".mcp.json"
    path.write_text(json.dumps({"mcpServers": servers}, ensure_ascii=False), encoding="utf-8")
    return path


def test_missing_file_returns_empty(tmp_path):
    servers, issues = load_mcp_config(tmp_path)
    assert servers == [] and issues == []


def test_load_valid_config(tmp_path):
    write_config(tmp_path, {"pet": {"type": "streamableHttp", "url": "http://127.0.0.1:8090/mcp"}})
    servers, issues = load_mcp_config(tmp_path)
    assert len(servers) == 1
    assert servers[0].name == "pet"
    assert servers[0].url == "http://127.0.0.1:8090/mcp"
    assert issues == []


def test_load_with_headers(tmp_path):
    write_config(
        tmp_path,
        {"s": {"url": "http://x/mcp", "headers": {"Authorization": "Bearer t"}}},
    )
    servers, _ = load_mcp_config(tmp_path)
    assert servers[0].headers["Authorization"] == "Bearer t"


def test_invalid_json_raises(tmp_path):
    (tmp_path / ".mcp.json").write_text("{bad json", encoding="utf-8")
    with pytest.raises(McpConfigError, match="不是合法 JSON"):
        load_mcp_config(tmp_path)


def test_missing_mcp_servers_key(tmp_path):
    (tmp_path / ".mcp.json").write_text('{"other": {}}', encoding="utf-8")
    with pytest.raises(McpConfigError, match="mcpServers"):
        load_mcp_config(tmp_path)


def test_missing_url_is_issue_not_error(tmp_path):
    write_config(tmp_path, {"a": {"type": "streamableHttp"}, "b": {"url": "http://ok/mcp"}})
    servers, issues = load_mcp_config(tmp_path)
    assert [s.name for s in servers] == ["b"]
    assert any("缺少 url" in str(i) for i in issues)


def test_bad_url_rejected(tmp_path):
    write_config(tmp_path, {"a": {"url": "ftp://x"}})
    servers, issues = load_mcp_config(tmp_path)
    assert servers == []
    assert any("http://" in str(i) for i in issues)


def test_unsupported_transport_rejected(tmp_path):
    write_config(tmp_path, {"a": {"type": "stdio", "url": "http://x/mcp"}})
    servers, issues = load_mcp_config(tmp_path)
    assert servers == []
    assert any("不支持的传输类型" in str(i) for i in issues)


# ---------------------------------------------------------------- 工具结果整理
class _TextItem:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeCallResult:
    def __init__(self, content=None, structured=None, is_error=False) -> None:
        self.content = content or []
        self.structured_content = structured
        self.is_error = is_error


def test_result_text_only():
    r = _to_call_result(_FakeCallResult(content=[_TextItem("hello")]))
    assert r.text == "hello"
    assert r.structured is None
    assert not r.is_error
    assert "hello" in r.render()


def test_result_structured_preferred():
    r = _to_call_result(
        _FakeCallResult(content=[_TextItem("see details")], structured={"total": 3})
    )
    rendered = r.render()
    assert '"total": 3' in rendered
    assert "see details" in rendered


def test_result_error_flag():
    r = _to_call_result(_FakeCallResult(content=[_TextItem("boom")], is_error=True))
    assert r.is_error
    assert "失败" in r.render()
    assert "boom" in r.render()


def test_result_structured_error():
    r = _to_call_result(
        _FakeCallResult(structured={"error": {"code": "X", "message": "权限不足"}}, is_error=True)
    )
    assert "权限不足" in r.render()


def test_result_empty():
    r = _to_call_result(_FakeCallResult())
    assert "没有返回内容" in r.render()


# ---------------------------------------------------------------- 命名与包装
def test_sanitize_server_name():
    assert _sanitize("pet-hospital") == "pet-hospital"
    assert _sanitize("my server!") == "my_server"
    # 纯符号会被兜底为 mcp
    assert _sanitize("!!!") == "mcp"
    # 中文是 isalnum 字符，会被保留（可读性更好）
    assert _sanitize("宠物医院") == "宠物医院"


def test_prefix_only_on_conflict():
    """auto 模式：无冲突时不加前缀，冲突时两边都加。"""
    manager = McpManager(prefix_mode="auto")
    manager._build_routes(
        [
            McpToolInfo("a", "unique", "d"),
            McpToolInfo("a", "dup", "d1"),
            McpToolInfo("b", "dup", "d2"),
        ]
    )
    names = set(manager._routes)
    assert "unique" in names
    assert "a__dup" in names
    assert "b__dup" in names


def test_prefix_always_mode():
    manager = McpManager(prefix_mode="always")
    manager._build_routes([McpToolInfo("srv", "tool", "d")])
    assert "srv__tool" in manager._routes


def test_no_prefix_mode():
    manager = McpManager(prefix_mode="never")
    manager._build_routes([McpToolInfo("a", "dup", "d"), McpToolInfo("b", "dup", "d")])
    # 第二个会因重名被加序号，仍能注册
    assert len(manager._routes) == 2


def test_route_map_preserves_original():
    manager = McpManager(prefix_mode="always")
    manager._build_routes([McpToolInfo("srv", "list_pets", "查询")])
    route = manager._routes["srv__list_pets"]
    assert route.server == "srv"
    assert route.original_name == "list_pets"


def test_wrapper_exposes_schema_and_desc():
    manager = McpManager()
    manager._build_routes(
        [
            McpToolInfo(
                "pet",
                "list_pets",
                "查询宠物",
                {"type": "object", "properties": {"status": {"type": "string"}}},
            )
        ]
    )
    tool = McpToolWrapper(manager.routes[0], manager)
    schema = tool.to_schema()["function"]
    assert schema["name"] == "list_pets"
    assert "[MCP:pet]" in schema["description"]
    assert "status" in schema["parameters"]["properties"]


def test_wrapper_forwards_arguments(monkeypatch):
    manager = McpManager()
    manager._build_routes([McpToolInfo("pet", "list_pets", "d")])
    captured = {}

    def fake_call(exposed, args):
        captured["exposed"] = exposed
        captured["args"] = args
        return "ok"

    monkeypatch.setattr(manager, "call", fake_call)
    tool = McpToolWrapper(manager.routes[0], manager)
    assert tool.run(status="住院中") == "ok"
    assert captured == {"exposed": "list_pets", "args": {"status": "住院中"}}


def test_build_mcp_tools_empty():
    assert build_mcp_tools(None) == []
    assert build_mcp_tools(McpManager()) == []


# ---------------------------------------------------------------- 容错
def test_call_unknown_tool():
    manager = McpManager()
    assert "未找到工具" in manager.call("nope", {})


def test_call_when_server_not_connected():
    manager = McpManager()
    manager._build_routes([McpToolInfo("pet", "list_pets", "d")])
    out = manager.call("list_pets", {})
    assert "未连接" in out


def test_manager_start_without_config(tmp_path):
    manager = McpManager()
    manager.start(project_root=tmp_path)
    assert manager.statuses == []
    assert manager.has_tools is False


def test_manager_start_with_broken_config(tmp_path):
    (tmp_path / ".mcp.json").write_text("{bad", encoding="utf-8")
    manager = McpManager()
    manager.start(project_root=tmp_path)          # 不应抛异常
    assert manager.issues
    assert manager.has_tools is False


def test_connect_failure_does_not_raise(tmp_path):
    write_config(tmp_path, {"dead": {"url": "http://127.0.0.1:1/mcp"}})
    manager = McpManager(connect_timeout=3.0)
    manager.start(project_root=tmp_path)
    assert len(manager.statuses) == 1
    assert manager.statuses[0].connected is False
    assert manager.statuses[0].error
    manager.close()


# ---------------------------------------------------------------- Prompt
def test_prompt_lists_connected_servers():
    manager = McpManager()
    manager._build_routes([McpToolInfo("pet", "list_pets", "d")])
    manager._statuses = [McpServerStatus("pet", "http://x/mcp", True, tool_count=1)]
    text = build_mcp_prompt(manager)
    assert "external MCP servers" in text
    assert "pet" in text and "list_pets" in text


def test_prompt_reports_unreachable():
    manager = McpManager()
    manager._statuses = [McpServerStatus("dead", "http://x/mcp", False, error="连接被拒绝")]
    text = build_mcp_prompt(manager)
    assert "unreachable" in text
    assert "连接被拒绝" in text


def test_prompt_empty_without_mcp():
    assert build_mcp_prompt(None) == ""
    assert build_mcp_prompt(McpManager()) == ""


# ---------------------------------------------------------------- 与本地工具共存
def test_mcp_tools_registered_alongside_local():
    from core.app import build_registry

    manager = McpManager()
    manager._build_routes([McpToolInfo("pet", "list_pets", "d")])
    manager._statuses = [McpServerStatus("pet", "http://x", True, 1)]

    registry = build_registry(mcp=manager)
    assert "list_pets" in registry.names
    # 本地工具仍在（loadSkill 需要技能才注册，故此处不列）
    for name in ("RunCli", "fetchWeb", "getCwd", "readFile", "createSkill"):
        assert name in registry.names


def test_local_tool_wins_on_name_clash():
    """MCP 工具与本地工具重名时保留本地实现。"""
    from core.app import build_registry

    manager = McpManager()
    manager._build_routes([McpToolInfo("pet", "getDate", "假的 getDate")])
    registry = build_registry(mcp=manager)

    spec = next(s for s in registry.schemas() if s["function"]["name"] == "getDate")
    assert "[MCP:" not in spec["function"]["description"]


# ---------------------------------------------------------------- 真实连接
def _server_alive(url: str) -> bool:
    try:
        from urllib.parse import urlparse

        parsed = urlparse(url)
        host, port = parsed.hostname, parsed.port or 80
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


REAL_URL = "http://127.0.0.1:8090/mcp"


@pytest.mark.skipif(not _server_alive(REAL_URL), reason="8090 MCP Server 未运行")
def test_real_server_discovery_and_call(tmp_path):
    write_config(tmp_path, {"pet": {"type": "streamableHttp", "url": REAL_URL}})
    manager = McpManager(connect_timeout=10.0, call_timeout=60.0)
    manager.start(project_root=tmp_path)
    try:
        assert manager.statuses[0].connected, manager.statuses[0].error
        assert manager.has_tools
        routes = [r.exposed_name for r in manager.routes]
        assert "list_pets" in routes

        out = manager.call("list_pets", {"status": "住院中"})
        assert "items" in out
    finally:
        manager.close()
