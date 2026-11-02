"""右侧栏：展示会话信息、已注册工具与已发现 Skill。"""

from __future__ import annotations

from rich.markup import escape
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static


class Sidebar(VerticalScroll):
    """会话信息 + 工具清单 + Skill 清单 + MCP 状态，可整体隐藏。"""

    def __init__(self, **kwargs) -> None:
        super().__init__(id="sidebar", **kwargs)
        self._session_box = Static(id="session-info")
        self._tools_box = Static(id="tools-info")
        self._skills_box = Static(id="skills-info")
        self._mcp_box = Static(id="mcp-info")

    def compose(self) -> ComposeResult:
        yield self._session_box
        yield self._tools_box
        yield self._skills_box
        yield self._mcp_box

    # ---------------------------------------------------------------- 会话
    def update_session(self, **info: str) -> None:
        """渲染会话信息。键名即显示的中文标签。"""
        rows = []
        for key, value in info.items():
            rows.append(f"[#6e7681]{escape(key)}[/]  {escape(str(value))}")
        self._session_box.update("[#58a6ff][b]会话[/b][/]\n" + "\n".join(rows))

    # ---------------------------------------------------------------- 工具
    def update_tools(self, specs: list[dict[str, str]]) -> None:
        if not specs:
            self._tools_box.update("[#58a6ff][b]工具 · 0[/b][/]")
            return

        lines = [f"[#58a6ff][b]工具 · {len(specs)}[/b][/]"]
        for item in specs:
            name = escape(item.get("name", ""))
            desc = escape(item.get("description", ""))
            if len(desc) > 60:
                desc = desc[:60] + "…"
            lines.append(f"[#7ee787][b]• {name}[/b][/]")
            lines.append(f"[#6e7681]  {desc}[/]")
        self._tools_box.update("\n".join(lines))

    # ---------------------------------------------------------------- Skill
    def update_skills(self, specs: list[dict[str, str]]) -> None:
        """Skill 用不同配色（紫），与工具区分开。"""
        if not specs:
            self._skills_box.update("[#58a6ff][b]技能 · 0[/b][/]")
            return

        lines = [f"[#58a6ff][b]技能 · {len(specs)}[/b][/]"]
        for item in specs:
            name = escape(item.get("name", ""))
            desc = escape(item.get("description", ""))
            if len(desc) > 56:
                desc = desc[:56] + "…"
            lines.append(f"[#d2a8ff][b]• {name}[/b][/]")
            lines.append(f"[#6e7681]  {desc}[/]")
        self._skills_box.update("\n".join(lines))

    # ---------------------------------------------------------------- MCP
    def update_mcp(self, statuses: list[dict[str, object]]) -> None:
        """MCP Server 连接状态。未配置时不占位。"""
        if not statuses:
            self._mcp_box.update("")
            return

        connected = sum(1 for s in statuses if s.get("connected"))
        lines = [f"[#58a6ff][b]MCP · {connected}/{len(statuses)}[/b][/]"]
        for status in statuses:
            name = escape(str(status.get("name", "")))
            if status.get("connected"):
                count = status.get("tool_count", 0)
                lines.append(f"[#7ee787][b]• {name}[/b][/]  [#6e7681]{count} 个工具[/]")
            else:
                error = escape(str(status.get("error", ""))[:40])
                lines.append(f"[#f85149][b]• {name}[/b][/]")
                lines.append(f"[#6e7681]  {error}[/]")
        self._mcp_box.update("\n".join(lines))
