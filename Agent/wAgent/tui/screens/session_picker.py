"""历史会话列表面板（/resume）。

↑↓ 选择、回车恢复、Esc 取消。也支持数字键快速选择。
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

from rich.markup import escape


class SessionPickerScreen(ModalScreen):
    """选择要恢复的会话。"""

    BINDINGS = [
        ("escape", "dismiss", "取消"),
        ("up", "move(-1)", "上移"),
        ("down", "move(1)", "下移"),
        ("enter", "confirm", "恢复"),
    ]

    CSS = """
    SessionPickerScreen {
        align: center middle;
        background: #0d1117 75%;
    }

    #picker-box {
        width: 88;
        height: auto;
        max-height: 85%;
        background: #010409;
        border: round #58a6ff;
        padding: 1 2 1 2;
    }

    #picker-title {
        height: 2;
        color: #58a6ff;
        text-style: bold;
    }

    #picker-list {
        height: auto;
        max-height: 20;
    }

    .session-item {
        height: 1;
        padding: 0 1 0 1;
        color: #c9d1d9;
    }

    .session-item.selected {
        background: #1f6feb;
        color: #ffffff;
        text-style: bold;
    }

    #picker-hint {
        height: 1;
        color: #6e7681;
        margin-top: 1;
    }
    """

    def __init__(self, sessions: list, **kwargs) -> None:
        super().__init__(**kwargs)
        self._sessions = list(sessions)
        self._index = 0
        self._chosen = None

    # ---------------------------------------------------------------- 布局
    def compose(self) -> ComposeResult:
        with Vertical(id="picker-box"):
            yield Static(
                f"历史会话（共 {len(self._sessions)} 个）", id="picker-title"
            )
            with VerticalScroll(id="picker-list"):
                if not self._sessions:
                    yield Static(
                        "还没有保存过任何会话。用 /new 或 /save 可创建。",
                        classes="session-item",
                    )
                else:
                    for i, meta in enumerate(self._sessions):
                        # 标题来自用户提问，可能含方括号，需转义
                        yield Static(
                            escape(f"{i + 1:>2}. {meta.display()}"),
                            classes="session-item",
                            id=f"session-{i}",
                        )
            yield Static(
                "↑↓ 选择 · Enter 恢复 · Esc 取消 · 数字键快速选择", id="picker-hint"
            )

    def on_mount(self) -> None:
        self._highlight()

    def _highlight(self) -> None:
        for i in range(len(self._sessions)):
            try:
                self.query_one(f"#session-{i}", Static).set_class(
                    i == self._index, "selected"
                )
            except Exception:  # noqa: BLE001
                pass

    # ---------------------------------------------------------------- 交互
    def action_move(self, delta: int) -> None:
        if not self._sessions:
            return
        self._index = (self._index + delta) % len(self._sessions)
        self._highlight()

    def action_confirm(self) -> None:
        if self._sessions and 0 <= self._index < len(self._sessions):
            self._chosen = self._sessions[self._index]
            self.dismiss(self._chosen)
        else:
            self.dismiss(None)

    def action_dismiss(self, result=None) -> None:
        self._chosen = None
        self.dismiss(None)

    def on_key(self, event) -> None:
        """数字键 1-9 直接选择。"""
        if not self._sessions:
            return
        if event.key.isdigit():
            idx = int(event.key) - 1
            if 0 <= idx < len(self._sessions):
                self._index = idx
                self._highlight()
                self.action_confirm()

    @property
    def chosen(self):
        return self._chosen


__all__ = ["SessionPickerScreen"]
