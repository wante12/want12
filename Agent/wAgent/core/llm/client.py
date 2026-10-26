"""LLM 客户端封装。

把 OpenAI SDK 的细节隔离在这一层：
- Agent 引擎只依赖 LLMClient 协议，不直接 import openai
- 流式增量解析成结构化片段，供上层转成领域事件
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Iterator

from ..config import LLMSettings


@dataclass
class ToolCallDelta:
    """流式返回里累积中的一个工具调用。"""

    index: int = 0
    id: str = ""
    type: str = "function"
    name: str = ""
    arguments: str = ""

    def to_message_dict(self) -> dict[str, Any]:
        """转成可回填进 messages 的 assistant.tool_calls 条目。"""
        return {
            "id": self.id,
            "type": self.type or "function",
            "function": {"name": self.name, "arguments": self.arguments},
        }


@dataclass
class StreamChunk:
    """一次流式增量：可能只有文本，也可能带工具调用分片。"""

    text: str = ""
    tool_calls: list[ToolCallDelta] = field(default_factory=list)


class LLMClient(ABC):
    """LLM 客户端协议，便于测试时替换成假实现。"""

    @abstractmethod
    def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> Iterator[StreamChunk]:
        """流式请求模型，逐块产出 StreamChunk。"""


class OpenAICompatClient(LLMClient):
    """OpenAI 兼容接口实现（DeepSeek 等）。"""

    def __init__(self, settings: LLMSettings, timeout: float = 120.0) -> None:
        try:
            from openai import OpenAI
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("缺少 openai 库，请先 pip install openai") from exc

        self._model = settings.model
        self._client = OpenAI(
            base_url=settings.base_url,
            api_key=settings.api_key,
            timeout=timeout,
        )

    def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> Iterator[StreamChunk]:
        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "stream": True,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        stream = self._client.chat.completions.create(**kwargs)

        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta

            deltas: list[ToolCallDelta] = []
            for tc in delta.tool_calls or []:
                function = tc.function
                deltas.append(
                    ToolCallDelta(
                        index=tc.index if tc.index is not None else 0,
                        id=tc.id or "",
                        type=tc.type or "",
                        name=(function.name if function and function.name else ""),
                        arguments=(function.arguments if function and function.arguments else ""),
                    )
                )

            yield StreamChunk(text=delta.content or "", tool_calls=deltas)


def merge_tool_calls(chunks: list[ToolCallDelta]) -> list[ToolCallDelta]:
    """把同一 index 的分片按顺序合并成完整工具调用。

    流式协议会把 name / arguments 拆成多个片段，index 相同的属于同一个调用。
    """
    merged: dict[int, ToolCallDelta] = {}
    for c in chunks:
        entry = merged.setdefault(c.index, ToolCallDelta(index=c.index))
        if c.id:
            entry.id = c.id
        if c.type:
            entry.type = c.type
        entry.name += c.name
        entry.arguments += c.arguments
    return [merged[i] for i in sorted(merged)]
