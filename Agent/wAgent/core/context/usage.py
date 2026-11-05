"""当前上下文用量的统一表示。

优先使用 API 返回的真实 token 数；没有时按消息内容估算。
阈值来自 config.ini 的 [context] 段，模块常量仅作兜底。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .tokens import (
    context_window_for,
    count_messages_tokens,
    count_tools_tokens,
    format_k,
)

#: 兜底阈值（config.ini 未提供时使用）
WARN_RATIO = 0.70
DANGER_RATIO = 0.85


@dataclass
class ContextUsage:
    """一次用量快照。"""

    used: int                  #: 当前上下文占用（token）
    window: int                #: 模型上下文窗口
    window_is_default: bool    #: 窗口大小是否为默认推测值
    measured_by_api: bool      #: used 是否来自 API 的真实 usage
    warn_ratio: float = WARN_RATIO
    danger_ratio: float = DANGER_RATIO

    @property
    def ratio(self) -> float:
        return self.used / self.window if self.window else 0.0

    @property
    def percent(self) -> float:
        return self.ratio * 100

    @property
    def needs_compact(self) -> bool:
        return self.ratio >= self.warn_ratio

    @property
    def is_danger(self) -> bool:
        return self.ratio >= self.danger_ratio

    def label(self) -> str:
        """状态栏显示用的一行文本。"""
        default_note = "（默认）" if self.window_is_default else ""
        text = (
            f"上下文 {format_k(self.used)} / {format_k(self.window)}{default_note}"
            f" · {self.percent:.0f}%"
        )
        if not self.measured_by_api:
            text += " · 估算"
        return text

    @classmethod
    def compute(
        cls,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        model: str,
        api_prompt_tokens: int | None = None,
        default_window: int | None = None,
        warn_ratio: float | None = None,
        danger_ratio: float | None = None,
    ) -> "ContextUsage":
        """计算用量。

        api_prompt_tokens 为 API 返回的 prompt_tokens——它已包含
        System Prompt、历史消息与工具定义，是最准确的来源。
        """
        window, is_default = context_window_for(model, default_window)

        if api_prompt_tokens and api_prompt_tokens > 0:
            return cls(
                used=api_prompt_tokens,
                window=window,
                window_is_default=is_default,
                measured_by_api=True,
                warn_ratio=warn_ratio if warn_ratio is not None else WARN_RATIO,
                danger_ratio=danger_ratio if danger_ratio is not None else DANGER_RATIO,
            )

        estimated = count_messages_tokens(messages) + count_tools_tokens(tools)
        return cls(
            used=estimated,
            window=window,
            window_is_default=is_default,
            measured_by_api=False,
            warn_ratio=warn_ratio if warn_ratio is not None else WARN_RATIO,
            danger_ratio=danger_ratio if danger_ratio is not None else DANGER_RATIO,
        )


__all__ = ["DANGER_RATIO", "WARN_RATIO", "ContextUsage"]

