"""聊天消息卡片：用户 / 助手 / 错误。

统一用「左侧色条 + 角色标题 + 正文」的结构，与参考界面一致。
"""

from __future__ import annotations

from rich.markup import escape
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static


class MessageCard(Vertical):
    """消息基类。子类通过 role_label / css_class 区分样式。"""

    role_label: str = ""
    variant: str = "assistant"

    def __init__(self, text: str = "", **kwargs) -> None:
        super().__init__(classes=f"msg msg-{self.variant}", **kwargs)
        self._text = text
        self._role = Static(escape(self.role_label), classes="role", markup=False)
        self._body = Static(escape(text), classes="msg-body", markup=False)

    def compose(self) -> ComposeResult:
        yield self._role
        yield self._body

    # -- 供流式更新使用 --
    def set_text(self, text: str) -> None:
        self._text = text
        self._body.update(escape(text))

    def append_text(self, piece: str) -> None:
        self.set_text(self._text + piece)

    @property
    def text(self) -> str:
        return self._text


class UserMessage(MessageCard):
    role_label = "你"
    variant = "user"


class AssistantMessage(MessageCard):
    role_label = "xAgent"
    variant = "assistant"


class ErrorMessage(MessageCard):
    role_label = "错误"
    variant = "error"
