"""把 MCP Server 信息渲染成 System Prompt 片段。

目的：让模型知道哪些工具来自外部 MCP Server，
以及在服务器连不上时应该如何向用户说明。
"""

from __future__ import annotations

from .manager import McpManager


def build_mcp_prompt(manager: McpManager | None) -> str:
    """生成 MCP 段落；没有配置也没有问题时返回空串。"""
    if manager is None:
        return ""
    if not manager.statuses and not manager.issues:
        return ""

    lines: list[str] = []
    connected = [s for s in manager.statuses if s.connected]
    failed = [s for s in manager.statuses if not s.connected]

    if connected and manager.has_tools:
        lines.append("You also have access to tools provided by external MCP servers:")
        for status in connected:
            names = [r.exposed_name for r in manager.routes if r.server == status.name]
            lines.append(f"- {status.name}: {', '.join(names)}")
        lines.append(
            "These MCP tools behave exactly like your local tools; call them normally."
        )

    if failed:
        if lines:
            lines.append("")
        lines.append("The following MCP servers are currently unreachable:")
        for status in failed:
            lines.append(f"- {status.name} ({status.url}): {status.error}")
        lines.append(
            "If the user asks for one of those tools, explain that the MCP server "
            "is not available and suggest starting it; do not pretend it succeeded."
        )

    if manager.issues:
        if lines:
            lines.append("")
        lines.append("MCP configuration problems:")
        lines.extend(f"- {issue}" for issue in manager.issues)

    return "\n".join(lines)


__all__ = ["build_mcp_prompt"]
