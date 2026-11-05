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
        system_prompt_extra: str = "",
        model_name: str = "",
        context_settings=None,
    ) -> None:
        self._settings = settings
        self._client = client
        self._registry = registry
        self._model_name = model_name
        self._context_settings = context_settings
        self._system_prompt = self._compose(settings.system_prompt, system_prompt_extra)
        self._messages: list[dict[str, Any]] = [
            {"role": "system", "content": self._system_prompt}
        ]
        #: 上一次 API 返回的 prompt_tokens（最准确的用量来源）
        self._last_prompt_tokens: int | None = None
        #: 压缩期间置为 True：禁止执行工具、禁止处理新任务
        self._compacting = False

    @staticmethod
    def _compose(base: str, extra: str) -> str:
        extra = (extra or "").strip()
        return f"{base}\n\n{extra}" if extra else base

    # ------------------------------------------------------------------ 状态
    @property
    def system_prompt(self) -> str:
        """实际发送给模型的 System Prompt（含技能清单等扩展段）。"""
        return self._system_prompt

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

    @property
    def tool_schemas(self) -> list[dict[str, Any]]:
        """工具定义原文，用于计算上下文占用。"""
        return self._registry.schemas()

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def is_compacting(self) -> bool:
        return self._compacting

    def context_usage(self) -> "ContextUsage":
        """当前上下文的 token 用量快照。阈值与默认窗口来自配置。"""
        from ..context import ContextUsage

        settings = self._context_settings
        return ContextUsage.compute(
            self._messages,
            self.tool_schemas,
            self._model_name,
            api_prompt_tokens=self._last_prompt_tokens,
            default_window=getattr(settings, "default_window", None),
            warn_ratio=getattr(settings, "warn_ratio", None),
            danger_ratio=getattr(settings, "danger_ratio", None),
        )

    def set_compacting(self, value: bool) -> None:
        """由 UI 在压缩开始/结束时调用。"""
        self._compacting = bool(value)

    def replace_context(self, messages: list[dict[str, Any]]) -> None:
        """用压缩后的消息列表替换当前上下文。

        System Prompt 始终保留**当前 Agent 自己的**版本——
        即使传入的列表里带了别的 system 消息，也不会覆盖，
        这样技能清单、MCP 说明等基本能力不受压缩影响。
        """
        rest = [m for m in messages if m.get("role") != "system"]
        self._messages = [{"role": "system", "content": self._system_prompt}] + rest
        self._last_prompt_tokens = None  # 旧用量已失效

    def append_message(self, message: dict[str, Any]) -> None:
        """向历史追加一条消息（用于 AGENTS.md 注入、恢复会话等）。"""
        if message:
            self._messages.append(dict(message))
            self._last_prompt_tokens = None

    def register_tools(self, tools: list[Any]) -> list[str]:
        """运行时注册新工具（MCP 异步加载后调用）。

        返回实际注册成功的工具名；重名的跳过，保证本地工具优先。
        """
        added: list[str] = []
        for tool in tools or []:
            name = getattr(tool, "name", "")
            if not name or name in self._registry.names:
                continue
            try:
                self._registry.register(tool)
                added.append(name)
            except Exception:  # noqa: BLE001 单个工具失败不影响其余
                continue
        if added:
            self._last_prompt_tokens = None
        return added

    def set_messages(self, messages: list[dict[str, Any]]) -> None:
        """直接设置历史（保留 System Prompt）。等价于 replace_context。"""
        self.replace_context(messages)

    def reset(self) -> None:
        """清空对话，保留 system prompt（含技能清单）。"""
        self._messages = [{"role": "system", "content": self._system_prompt}]
        self._last_prompt_tokens = None

    # ------------------------------------------------------------------ 主流程
    def stream_reply(self, user_prompt: str) -> Iterator[AgentEvent]:
        """处理一轮用户输入，逐条产出事件。

        失败或中断时回滚本轮消息，保证上下文干净（与原实现一致）。
        """
        if self._compacting:
            raise RuntimeError("正在压缩上下文，暂不接受新任务。请等待压缩完成。")

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
                usage = self.context_usage()
                yield AgentEvent(
                    EventType.ROUND_FINISHED,
                    {
                        "content": content,
                        "duration_ms": round((time.perf_counter() - round_started) * 1000, 1),
                        "tool_calls": tool_calls_made,
                        "context_used": usage.used,
                        "context_window": usage.window,
                        "context_percent": round(usage.percent, 1),
                        "context_warn": usage.needs_compact,
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
            # 流末尾可能带 usage，记下来作为上下文占用
            if getattr(chunk, "usage", None) is not None:
                prompt_tokens = getattr(chunk.usage, "prompt_tokens", 0) or 0
                if prompt_tokens > 0:
                    self._last_prompt_tokens = prompt_tokens

        return "".join(text_parts), merge_tool_calls(call_deltas), events

    def _execute_tools(self, tool_calls: list[ToolCallDelta]) -> Iterator[AgentEvent]:
        """依次执行工具，并把结果作为 tool 消息回填。"""
        import json
        import time

        if self._compacting:
            # 压缩期间禁止任何工具执行
            return

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
