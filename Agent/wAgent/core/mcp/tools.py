"""把 MCP 工具包装成 wAgent 的本地 Tool。

这样 MCP 工具与 RunCli / fetchWeb / loadSkill 等走完全相同的
Function Calling 通道：注册进 ToolRegistry，由 Agent 循环统一调用。
"""

from __future__ import annotations

from typing import Any

from ..tools.base import Tool
from .manager import McpManager, McpToolRoute


class McpToolWrapper(Tool):
    """一个 MCP 工具的本地代理。

    name / description / parameters 来自 MCP 的 list_tools()，
    执行时转发给对应的 MCP Server。
    """

    def __init__(self, route: McpToolRoute, manager: McpManager) -> None:
        self._route = route
        self._manager = manager

        self.name = route.exposed_name
        base_desc = route.description.strip() or f"MCP 工具 {route.original_name}"
        # 让模型知道工具来自哪个服务器，便于理解与排错
        self.description = f"[MCP:{route.server}] {base_desc}"
        # 参数 Schema 直接沿用服务器给的
        schema = route.input_schema or {}
        if not isinstance(schema.get("type"), str):
            schema = {"type": "object", "properties": {**schema}} if schema.get(
                "properties"
            ) else {"type": "object", "properties": {}, "additionalProperties": False}
        self.parameters = schema

    def run(self, **kwargs: Any) -> str:
        return self._manager.call(self._route.exposed_name, dict(kwargs))

    # 便于调试与 UI 展示
    @property
    def server(self) -> str:
        return self._route.server

    @property
    def original_name(self) -> str:
        return self._route.original_name


def build_mcp_tools(manager: McpManager | None) -> list[Tool]:
    """把已发现的 MCP 工具包装成 Tool 列表；无管理器时返回空列表。"""
    if manager is None or not manager.has_tools:
        return []
    return [McpToolWrapper(route, manager) for route in manager.routes]


__all__ = ["McpToolWrapper", "build_mcp_tools"]
