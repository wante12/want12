"""压缩结果对比面板。

左右两栏：
    左侧 = 压缩前的原始上下文（转录后的纯文本）
    右侧 = 压缩后的摘要

两栏各自可独立滚动（鼠标滚轮 / 键盘），底部有关闭按钮。
按 Esc 或点「关闭」都能退出。
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Markdown, Static

from rich.markup import escape


class CompactCompareScreen(ModalScreen):
    """压缩前后对比。"""

    CSS = """
    CompactCompareScreen {
        align: center middle;
        background: #0d1117 75%;
    }

    #compare-box {
        width: 96%;
        height: 92%;
        background: #0d1117;
        border: round #58a6ff;
        padding: 1 2 1 2;
    }

    #compare-title {
        height: 2;
        color: #58a6ff;
        text-style: bold;
    }

    #compare-body {
        height: 1fr;
    }

    .compare-pane {
        width: 1fr;
        border: round #30363d;
        padding: 0 1 0 1;
    }

    #compare-left { border: round #f0883e; }
    #compare-right { border: round #3fb950; }

    .pane-header {
        height: 1;
        text-style: bold;
    }

    #left-header { color: #f0883e; }
    #right-header { color: #3fb950; }

    .pane-scroll {
        height: 1fr;
        scrollbar-size-vertical: 1;
    }

    .pane-text {
        padding: 0 1 0 0;
    }

    #compare-footer {
        height: 3;
        align-horizontal: right;
        padding: 1 0 0 0;
    }
    """

    BINDINGS = [
        ("escape", "dismiss", "关闭"),
        ("q", "dismiss", "关闭"),
    ]

    def __init__(
        self,
        before_text: str,
        after_text: str,
        *,
        archive_id: str = "",
        before_tokens: int = 0,
        after_tokens: int = 0,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._before = before_text or "(无内容)"
        self._after = after_text or "(无内容)"
        self._archive_id = archive_id
        self._before_tokens = before_tokens
        self._after_tokens = after_tokens

    # ---------------------------------------------------------------- 布局
    def compose(self) -> ComposeResult:
        title = (
            f"上下文压缩完成 · {self._before_tokens / 1024:.1f}k → "
            f"{self._after_tokens / 1024:.1f}k tokens"
        )
        if self._archive_id:
            title += f" · 归档 {self._archive_id}"

        with Vertical(id="compare-box"):
            yield Static(escape(title), id="compare-title")

            with Horizontal(id="compare-body"):
                with Vertical(id="compare-left", classes="compare-pane"):
                    yield Static(
                        f"压缩前原始上下文（{self._before_tokens / 1024:.1f}k）",
                        id="left-header",
                        classes="pane-header",
                    )
                    with VerticalScroll(classes="pane-scroll"):
                        # 原始转录里必然有 [0] user 这类方括号索引，
                        # 必须关掉 markup 解析，否则渲染会报 Expected markup value
                        yield Static(self._before, classes="pane-text", markup=False)

                with Vertical(id="compare-right", classes="compare-pane"):
                    yield Static(
                        f"压缩后摘要（{self._after_tokens / 1024:.1f}k）",
                        id="right-header",
                        classes="pane-header",
                    )
                    with VerticalScroll(classes="pane-scroll"):
                        yield Markdown(self._after)

            with Horizontal(id="compare-footer"):
                yield Button("关闭 (Esc)", variant="primary", id="close-btn")

    # ---------------------------------------------------------------- 交互
    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "close-btn":
            self.action_dismiss()

    def action_dismiss(self, result=None) -> None:
        self.dismiss(None)
