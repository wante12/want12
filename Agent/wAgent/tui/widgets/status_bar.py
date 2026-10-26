"""底部状态栏：就绪状态、轮次、工具次数、耗时。"""

from __future__ import annotations

from rich.markup import escape
from textual.widgets import Static


class StatusBar(Static):
    """单行状态提示，界面底部。"""

    def __init__(self, **kwargs) -> None:
        super().__init__(id="statusbar", **kwargs)
        self._status = "就绪"
        self._style = "ok"
        self._rounds = 0
        self._tools = 0
        self._elapsed = ""
        self._model = ""

    # ---------------------------------------------------------------- 设置
    def configure(self, model: str) -> None:
        self._model = model
        self.refresh_text()

    def set_state(self, status: str, style: str = "ok") -> None:
        self._status = status
        self._style = style
        self.refresh_text()

    def add_round(self, tool_calls: int = 0, duration_ms: float | None = None) -> None:
        self._rounds += 1
        self._tools += tool_calls
        if duration_ms is not None:
            self._elapsed = f"{duration_ms / 1000:.1f}s"
        self.refresh_text()

    def reset_counters(self) -> None:
        self._rounds = 0
        self._tools = 0
        self._elapsed = ""
        self.refresh_text()

    # ---------------------------------------------------------------- 渲染
    def refresh_text(self) -> None:
        dot = {"ok": "[#3fb950]●[/]", "busy": "[#d29922]●[/]", "err": "[#f85149]●[/]"}[
            self._style
        ]
        parts = [f"{dot} {escape(self._status)}", f"{self._rounds} 轮"]
        if self._model:
            parts.append(escape(self._model))
        parts.append(f"工具 {self._tools} 次")
        if self._elapsed:
            parts.append(self._elapsed)
        parts.append("Esc 中断")
        self.update("  ·  ".join(parts))
