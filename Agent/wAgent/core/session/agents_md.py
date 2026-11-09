"""AGENTS.md 项目指令加载。

策略：**一次注入，全程复用**
    - 会话首次加载时读取 <项目根>/AGENTS.md
    - 作为一条 user 消息追加到聊天历史
    - 随会话保存到事件日志（JSONL），后续轮次直接复用
    - 不在每轮重复注入，保证 prompt 前缀稳定、命中缓存

这样做的好处：一旦首轮把 AGENTS.md 写入历史，后续请求的 messages
前缀完全一致，服务端 prompt cache 可以持续命中。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

#: 默认文件名（可被 config.ini 的 [session] agents_md 覆盖）
AGENTS_FILE = "AGENTS.md"
#: 兼容的单数写法。两种文件名都会被识别，优先使用复数形式。
AGENT_FILE_ALIASES = ("AGENT.md",)
#: 单文件长度上限，避免超大文件把上下文撑爆
MAX_CHARS = 60_000
#: 注入消息的前缀标记，用于识别「这条消息是否已注入」
INJECTION_MARKER = "[项目指令 AGENTS.md]"


@dataclass(frozen=True)
class AgentsMd:
    """读取到的项目指令。"""

    path: Path
    content: str

    @property
    def truncated(self) -> bool:
        return self._truncated

    _truncated: bool = False


def candidate_names(filename: str = AGENTS_FILE) -> tuple[str, ...]:
    """返回要查找的文件名候选（含单数兼容名）。

    若配置里指定了自定义文件名，只查该名字；
    否则依次尝试 AGENTS.md、AGENT.md。
    """
    if filename and filename != AGENTS_FILE:
        return (filename,)
    return (AGENTS_FILE, *AGENT_FILE_ALIASES)


def find_agents_md(
    project_root: Path | str | None = None,
    filename: str = AGENTS_FILE,
) -> Path | None:
    """在项目根查找项目指令文件，返回路径或 None。

    兼容 AGENTS.md 与 AGENT.md 两种写法，前者优先。
    """
    root = Path(project_root) if project_root else Path.cwd()
    for name in candidate_names(filename):
        path = root / name
        if path.is_file():
            return path
    return None


def load_agents_md(
    project_root: Path | str | None = None,
    filename: str = AGENTS_FILE,
    max_chars: int = MAX_CHARS,
) -> AgentsMd | None:
    """读取 AGENTS.md。不存在或为空时返回 None。"""
    path = find_agents_md(project_root, filename)
    if path is None:
        return None

    try:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return None

    text = text.strip()
    if not text:
        return None

    truncated = False
    if len(text) > max_chars:
        text = text[:max_chars] + f"\n\n…（AGENTS.md 过长，已截断到 {max_chars} 字符）"
        truncated = True

    return AgentsMd(path=path, content=text, _truncated=truncated)


def build_injection_message(agents: AgentsMd) -> dict[str, str]:
    """构造要追加到历史的那条消息。

    用 user 角色而不是 system：
    - 不干扰 System Prompt（保持技能/MCP 段稳定）
    - 作为普通历史消息参与缓存前缀
    """
    return {
        "role": "user",
        "content": (
            f"{INJECTION_MARKER}\n"
            f"以下是本项目的约定与要求，请在本次会话中始终遵守：\n\n"
            f"{agents.content}"
        ),
    }


def is_injected(messages: list[dict]) -> bool:
    """判断当前历史里是否已注入过 AGENTS.md。"""
    for message in messages:
        content = message.get("content")
        if isinstance(content, str) and content.startswith(INJECTION_MARKER):
            return True
    return False


__all__ = [
    "AGENTS_FILE",
    "INJECTION_MARKER",
    "MAX_CHARS",
    "AgentsMd",
    "build_injection_message",
    "find_agents_md",
    "is_injected",
    "load_agents_md",
]
