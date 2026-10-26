"""工具调用的可折叠卡片。

运行中显示黄色左条与「运行中…」，完成后变绿并显示耗时，
内容分「参数」「结果」两段，可点击展开。
"""

from __future__ import annotations

import json

from rich.markup import escape
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Collapsible, Static


class ToolCard(Vertical):
    """一次工具调用的展示单元。"""

    def __init__(self, name: str, arguments: dict | None = None, **kwargs) -> None:
        super().__init__(classes="tool-card running", **kwargs)
        self._name = name
        self._arguments = arguments or {}

        self._params_label = Static("参数", classes="section-label")
        self._params_body = Static(
            escape(json.dumps(self._arguments, ensure_ascii=False, indent=2)),
            classes="section-body",
            markup=False,
        )
        self._result_label = Static("结果", classes="section-label")
        self._result_body = Static("执行中…", classes="section-body", markup=False)

        self._collapsible = Collapsible(
            self._params_label,
            self._params_body,
            self._result_label,
            self._result_body,
            title=self._running_title(),
            collapsed=True,
        )

    # ---------------------------------------------------------------- 标题
    def _args_summary(self) -> str:
        if not self._arguments:
            return "()"
        parts = []
        for k, v in self._arguments.items():
            text = json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v
            if len(text) > 40:
                text = text[:40] + "…"
            parts.append(f"{k}={text}")
        return "(" + ", ".join(parts) + ")"

    def _running_title(self) -> str:
        return f"⟳ {self._name}{self._args_summary()} · 运行中…"

    def _done_title(self, duration_ms: float | None) -> str:
        suffix = f" · {duration_ms:.0f} ms" if duration_ms is not None else ""
        return f"{self._name}{self._args_summary()}{suffix}"

    # ---------------------------------------------------------------- 布局
    def compose(self) -> ComposeResult:
        yield self._collapsible

    # ---------------------------------------------------------------- 完成
    def finish(self, result: str, duration_ms: float | None = None) -> None:
        """工具执行完成后回填结果并切换配色。"""
        self.remove_class("running")
        self._collapsible.title = self._done_title(duration_ms)
        self._result_body.update(escape(result or "(无输出)"))

    @property
    def tool_name(self) -> str:
        return self._name
