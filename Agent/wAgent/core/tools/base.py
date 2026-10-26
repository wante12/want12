"""工具抽象与注册表。

新增工具只需写一个 Tool 子类并注册，Agent 引擎无需改动（开闭原则）。
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any


class ToolError(Exception):
    """工具执行失败。"""


class Tool(ABC):
    """所有工具的基类。

    子类需提供 name / description / parameters，并实现 run()。
    parameters 必须是 JSON Schema（object 类型），直接用于 LLM function calling。
    """

    name: str
    description: str
    parameters: dict[str, Any] = {"type": "object", "properties": {}, "additionalProperties": False}

    @abstractmethod
    def run(self, **kwargs: Any) -> str:
        """执行工具，返回给模型的文本结果。失败时抛 ToolError 或任意异常。"""

    def to_schema(self) -> dict[str, Any]:
        """转成 OpenAI function calling 的 tools 条目。"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolRegistry:
    """工具注册表：负责登记、导出 schema、分发执行。"""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"工具重名: {tool.name}")
        self._tools[tool.name] = tool

    def schemas(self) -> list[dict[str, Any]]:
        return [t.to_schema() for t in self._tools.values()]

    @property
    def names(self) -> list[str]:
        return list(self._tools)

    def execute(self, name: str, arguments_json: str) -> str:
        """解析参数并执行工具。

        任何失败都转成可读字符串返回给模型，不向 UI 抛异常
        （Agent 循环需要继续，工具失败本身是一种可回传的信息）。
        """
        tool = self._tools.get(name)
        if tool is None:
            return f"未知工具: {name}"

        try:
            arguments = json.loads(arguments_json) if arguments_json else {}
        except json.JSONDecodeError as exc:
            return f"工具参数解析失败: {exc}"

        if not isinstance(arguments, dict):
            return f"工具参数必须是对象，实际为 {type(arguments).__name__}"

        try:
            return str(tool.run(**arguments))
        except TypeError as exc:
            return f"工具 {name} 参数不匹配: {exc}"
        except Exception as exc:  # noqa: BLE001 工具异常统一回传
            return f"工具 {name} 执行失败: {exc}"
