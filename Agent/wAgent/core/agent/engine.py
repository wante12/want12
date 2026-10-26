"""Agent 引擎：对话循环与工具编排。

职责边界：
- 维护对话消息历史
- 驱动 LLM 流式输出
- 解析并执行工具调用，把结果回填给模型
- 以领域事件（AgentEvent）形式对外广播过程

不做任何渲染：不 print、不读终端、不依赖 UI。
"""

from __future__ import annotations

from typing import Any, Iterator

from ..config import AgentSettings
from ..events import AgentEvent, EventType
from ..llm.client import LLMClient, ToolCallDelta, merge_tool_calls
from ..tools.base import ToolRegistry


class Agent:
    """可复用的 Agent 核心。

    用法：
        agent = Agent(settings, client, registry)
        for event in agent.stream_reply("今天是几号？"):
            ...  # 由 UI 层决定如何展示
    """

    def __init__(
        self,
        settings: AgentSettings,
        client: LLMClient,
        registry: ToolRegistry,
    ) -> None:
        self._settings = settings
        self._client = client
        self._registry = registry
        self._messages: list[dict[str, Any]] = [
            {"role": "system", "content": settings.system_prompt}
        ]

    # ------------------------------------------------------------------ 状态
    @property
    def history(self) -> list[dict[str, Any]]:
        """当前对话历史（只读副本）。"""
        return [dict(m) for m in self._messages]

    @property
    def tool_names(self) -> list[str]:
        """已注册的工具名，供 UI 展示或调试。"""
        return self._registry.names

    @property
    def tool_specs(self) -> list[dict[str, str]]:
        """已注册工具的「名称 + 说明」，供侧栏等 UI 展示。"""
        return [
            {"name": item["function"]["name"],
             "description": item["function"]["description"]}
            for item in self._registry.schemas()
        ]

    def reset(self) -> None:
        """清空对话，保留 system prompt。"""
        self._messages = [{"role": "system", "content": self._settings.system_prompt}]

    # ------------------------------------------------------------------ 主流程
    def stream_reply(self, user_prompt: str) -> Iterator[AgentEvent]:
        """处理一轮用户输入，逐条产出事件。

        失败或中断时回滚本轮消息，保证上下文干净（与原实现一致）。
        """
        start_len = len(self._messages)
        self._messages.append({"role": "user", "content": user_prompt})
        yield AgentEvent(EventType.ROUND_STARTED, {"prompt": user_prompt})

        import time

        round_started = time.perf_counter()
        tool_calls_made = 0

        try:
            for _ in range(self._settings.max_tool_rounds + 1):
                content, tool_calls, text_events = self._run_one_completion()
                yield from text_events

                if tool_calls:
                    self._messages.append(
                        {
                            "role": "assistant",
                            "content": content or None,
                            "tool_calls": [tc.to_message_dict() for tc in tool_calls],
                        }
                    )
                    tool_calls_made += len(tool_calls)
                    yield from self._execute_tools(tool_calls)
                    continue

                self._messages.append({"role": "assistant", "content": content})
                yield AgentEvent(
                    EventType.ROUND_FINISHED,
                    {
                        "content": content,
                        "duration_ms": round((time.perf_counter() - round_started) * 1000, 1),
                        "tool_calls": tool_calls_made,
                    },
                )
                return

            raise RuntimeError("工具调用次数过多，已停止本轮对话。")

        except BaseException:  # noqa: BLE001 含 KeyboardInterrupt，需回滚后重抛
            del self._messages[start_len:]
            raise

    # ------------------------------------------------------------------ 内部
    def _run_one_completion(self) -> tuple[str, list[ToolCallDelta], list[AgentEvent]]:
        """执行一次 LLM 请求，累积文本与工具调用分片。"""
        text_parts: list[str] = []
        call_deltas: list[ToolCallDelta] = []
        events: list[AgentEvent] = []

        for chunk in self._client.stream(self._messages, self._registry.schemas()):
            if chunk.text:
                text_parts.append(chunk.text)
                events.append(AgentEvent(EventType.TEXT_DELTA, {"text": chunk.text}))
            if chunk.tool_calls:
                call_deltas.extend(chunk.tool_calls)

        return "".join(text_parts), merge_tool_calls(call_deltas), events

    def _execute_tools(self, tool_calls: list[ToolCallDelta]) -> Iterator[AgentEvent]:
        """依次执行工具，并把结果作为 tool 消息回填。"""
        import json
        import time

        for tc in tool_calls:
            try:
                arguments = json.loads(tc.arguments) if tc.arguments else {}
            except json.JSONDecodeError:
                arguments = {}
            if not isinstance(arguments, dict):
                arguments = {}

            yield AgentEvent(
                EventType.TOOL_CALL_STARTED,
                {"name": tc.name, "arguments": arguments},
            )

            started = time.perf_counter()
            result = self._registry.execute(tc.name, tc.arguments)
            elapsed_ms = (time.perf_counter() - started) * 1000

            yield AgentEvent(
                EventType.TOOL_CALL_FINISHED,
                {"name": tc.name, "result": result, "duration_ms": round(elapsed_ms, 1)},
            )

            self._messages.append(
                {"role": "tool", "tool_call_id": tc.id, "content": result}
            )
