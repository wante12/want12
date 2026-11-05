"""上下文的 Token 计量。

优先使用模型 API 返回的 usage；拿不到时按字符数估算。

估算规则（中英混排的粗粒度近似，够用且好理解）：
- CJK 字符按 1 token 计
- 其余字符按 4 字符 1 token 计
这个比例对 DeepSeek / GPT 系的中文场景偏差通常在 20% 以内，
足以支撑「70% 阈值预警」这种量级的判断。
"""

from __future__ import annotations

import json
from typing import Any

#: 常见模型的上下文窗口（以 1024 为 1K）
MODEL_CONTEXT_WINDOWS: dict[str, int] = {
    # DeepSeek
    "deepseek-chat": 128 * 1024,
    "deepseek-reasoner": 128 * 1024,
    "deepseek-coder": 128 * 1024,
    # OpenAI
    "gpt-4o": 128 * 1024,
    "gpt-4o-mini": 128 * 1024,
    "gpt-4-turbo": 128 * 1024,
    "gpt-3.5-turbo": 16 * 1024,
    "o1": 200 * 1024,
    "o1-mini": 128 * 1024,
    # 通义 / 智谱
    "qwen-max": 32 * 1024,
    "qwen-plus": 128 * 1024,
    "qwen-turbo": 128 * 1024,
    "glm-4": 128 * 1024,
    # Anthropic（经兼容层）
    "claude-3-5-sonnet": 200 * 1024,
}

#: 无法识别模型时的默认窗口
DEFAULT_CONTEXT_WINDOW = 128 * 1024


def is_cjk(ch: str) -> bool:
    code = ord(ch)
    return (
        0x4E00 <= code <= 0x9FFF        # 中日韩统一表意文字
        or 0x3400 <= code <= 0x4DBF     # 扩展 A
        or 0x3000 <= code <= 0x303F     # 中文标点
        or 0xFF00 <= code <= 0xFFEF     # 全角字符
        or 0x3040 <= code <= 0x30FF     # 假名
    )


def count_text_tokens(text: str) -> int:
    """估算一段文本的 token 数。"""
    if not text:
        return 0
    cjk = sum(1 for ch in text if is_cjk(ch))
    others = len(text) - cjk
    return cjk + (others + 3) // 4


def _content_tokens(content: Any) -> int:
    """消息 content 可能是字符串，也可能是分片数组。"""
    if content is None:
        return 0
    if isinstance(content, str):
        return count_text_tokens(content)
    if isinstance(content, list):
        total = 0
        for part in content:
            if isinstance(part, dict):
                total += count_text_tokens(str(part.get("text", "")))
        return total
    return count_text_tokens(str(content))


def count_message_tokens(message: dict[str, Any]) -> int:
    """估算单条消息的 token 数（含工具调用与工具结果）。"""
    tokens = _content_tokens(message.get("content"))

    for call in message.get("tool_calls") or []:
        if not isinstance(call, dict):
            continue
        function = call.get("function") or {}
        tokens += count_text_tokens(str(function.get("name", "")))
        tokens += count_text_tokens(str(function.get("arguments", "")))
        tokens += 4  # 结构与 id 的固定开销

    # 每条消息的 role / 分隔符开销
    return tokens + 4


def count_messages_tokens(messages: list[dict[str, Any]]) -> int:
    """估算整段消息列表的 token 数。"""
    return sum(count_message_tokens(m) for m in messages)


def count_tools_tokens(tools: list[dict[str, Any]] | None) -> int:
    """估算工具定义（JSON Schema）的 token 数。

    工具定义同样占用上下文，必须计入，否则会低估。
    """
    if not tools:
        return 0
    return count_text_tokens(json.dumps(tools, ensure_ascii=False))


def context_window_for(model: str, default: int | None = None) -> tuple[int, bool]:
    """返回 (上下文窗口大小, 是否为默认值)。

    先精确匹配，再按前缀/包含关系模糊匹配（如 deepseek-chat-0324）。
    default 可由 config.ini 的 [context] default_window 覆盖。
    """
    fallback = default if default and default > 0 else DEFAULT_CONTEXT_WINDOW
    name = (model or "").strip().lower()
    if not name:
        return fallback, True

    if name in MODEL_CONTEXT_WINDOWS:
        return MODEL_CONTEXT_WINDOWS[name], False

    for key, size in MODEL_CONTEXT_WINDOWS.items():
        if name.startswith(key) or key in name:
            return size, False

    return fallback, True


def format_k(tokens: int) -> str:
    """把 token 数格式化成 '12.3k' 这种形式。"""
    return f"{tokens / 1024:.1f}k"


__all__ = [
    "DEFAULT_CONTEXT_WINDOW",
    "MODEL_CONTEXT_WINDOWS",
    "context_window_for",
    "count_message_tokens",
    "count_messages_tokens",
    "count_text_tokens",
    "count_tools_tokens",
    "format_k",
    "is_cjk",
]
