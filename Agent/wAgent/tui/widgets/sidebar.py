"""右侧栏：展示会话信息与已注册工具列表。"""

from __future__ import annotations

from rich.markup import escape
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static


class Sidebar(VerticalScroll):
    """会话信息 + 工具清单，可整体隐藏。"""

    def __init__(self, **kwargs) -> None:
        super().__init__(id="sidebar", **kwargs)
        self._session_box = Static(id="session-info")
        self._tools_box = Static(id="tools-info")

    def compose(self) -> ComposeResult:
        yield self._session_box
        yield self._tools_box

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
