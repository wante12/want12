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
class Usage:
    """一次请求的 token 用量（来自模型 API）。"""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class StreamChunk:
    """一次流式增量：可能只有文本，也可能带工具调用分片。

    usage 只在流结束时出现（OpenAI 兼容接口把它放在最后一个 chunk 里）。
    """

    text: str = ""
    tool_calls: list[ToolCallDelta] = field(default_factory=list)
    usage: Usage | None = None


class LLMClient(ABC):
    """LLM 客户端协议，便于测试时替换成假实现。"""

    @abstractmethod
    def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> Iterator[StreamChunk]:
        """流式请求模型，逐块产出 StreamChunk。"""

    def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> str:
        """非流式地拿到完整回复（供上下文压缩使用）。

        默认实现基于 stream() 拼装，子类可覆盖。
        """
        return "".join(chunk.text for chunk in self.stream(messages, tools))


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

    @property
    def model(self) -> str:
        return self._model

    def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> Iterator[StreamChunk]:
        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "stream": True,
            # 让服务端在流末尾附带 usage，用于上下文监控
            "stream_options": {"include_usage": True},
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        stream = self._client.chat.completions.create(**kwargs)

        for chunk in stream:
            raw_usage = getattr(chunk, "usage", None)
            usage = None
            if raw_usage is not None:
                usage = Usage(
                    prompt_tokens=int(getattr(raw_usage, "prompt_tokens", 0) or 0),
                    completion_tokens=int(getattr(raw_usage, "completion_tokens", 0) or 0),
                    total_tokens=int(getattr(raw_usage, "total_tokens", 0) or 0),
                )

            if not chunk.choices:
                # 只带 usage 的结尾块
                if usage is not None:
                    yield StreamChunk(usage=usage)
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

            yield StreamChunk(text=delta.content or "", tool_calls=deltas, usage=usage)


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
