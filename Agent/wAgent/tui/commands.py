"""斜杠命令解析与分发。

命令只影响界面与展示，不改动 core 的对话逻辑
（/new 会调用 Agent.reset，属于 core 的公开接口）。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CommandResult:
    """命令执行结果。"""

    handled: bool = False
    message: str = ""
    quit_app: bool = False


def parse(text: str) -> tuple[str, str]:
    """把 '/cmd rest' 拆成 ('/cmd', 'rest')；普通文本返回 ('', text)。"""
    stripped = text.strip()
    if not stripped.startswith("/"):
        return "", stripped
    head, _, rest = stripped.partition(" ")
    return head.lower(), rest.strip()


QUIT_ALIASES = {"/quit", "/exit", "/q"}
