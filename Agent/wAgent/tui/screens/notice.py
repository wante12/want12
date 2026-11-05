"""启动提示对话框。

用于：
- config.ini 是新建的模板（需要用户填 key 后重启）
- AGENTS.md 已注入的提示
其他需要用户「看完再继续」的一次性消息。
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Markdown, Static

from rich.markup import escape


class NoticeScreen(ModalScreen):
    """一个可滚动的提示面板。"""

    BINDINGS = [
        ("escape", "close", "关闭"),
        ("enter", "close", "关闭"),
    ]

    CSS = """
    NoticeScreen {
        align: center middle;
        background: #0d1117 80%;
    }

    #notice-box {
        width: 88;
        height: auto;
        max-height: 88%;
        background: #010409;
        border: round #d29922;
        padding: 1 2 1 2;
    }

    #notice-title {
        height: 2;
        color: #d29922;
        text-style: bold;
    }

    #notice-body {
        height: auto;
        max-height: 24;
    }

    #notice-footer {
        height: 3;
        align-horizontal: right;
        padding: 1 0 0 0;
    }
    """

    def __init__(self, title: str, body: str, *, quit_on_close: bool = False, **kwargs) -> None:
        super().__init__(**kwargs)
        self._title = title
        self._body = body
        self._quit_on_close = quit_on_close

    def compose(self) -> ComposeResult:
        with Vertical(id="notice-box"):
            yield Static(escape(self._title), id="notice-title")
            yield Markdown(self._body, id="notice-body")
            with Vertical(id="notice-footer"):
                yield Button("知道了", variant="primary", id="notice-ok")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.action_close()

    def action_close(self) -> None:
        self.app.pop_screen()
        if self._quit_on_close:
            try:
                self.app.exit()
            except Exception:  # noqa: BLE001
                pass


__all__ = ["NoticeScreen"]
