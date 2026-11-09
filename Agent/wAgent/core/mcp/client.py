"""MCP 客户端运行时。

wAgent 的 Agent 循环是**同步**的（`stream_reply` 是生成器），而 MCP Python SDK
是**异步**的。因此这里在后台线程里跑一个独立事件循环，把异步调用桥接成同步调用：

    主线程 (同步)  ──run_coroutine_threadsafe──▶  后台线程的事件循环 (异步)

每个 MCP Server 维护一个长连接（Streamable HTTP），
连接失败不影响其他 Server 与本地工具。
"""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass, field
from typing import Any

from .config import McpServerConfig


class McpConnectionError(Exception):
    """连接 MCP Server 失败。"""


class McpCallError(Exception):
    """调用 MCP 工具失败。"""


@dataclass
class McpToolInfo:
    """从 MCP Server 发现的工具元信息。"""

    server: str
    name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)


@dataclass
class McpCallResult:
    """工具调用结果。

    MCP 的返回可能有三种内容，这里统一整理：
    - 文本内容（TextContent 拼接）
    - 结构化数据（structuredContent）
    - 错误标记（isError / 结构化结果里的 error 字段）
    """

    text: str = ""
    structured: dict[str, Any] | None = None
    is_error: bool = False
    error_message: str = ""

    def render(self) -> str:
        """整理成给 LLM 看的文本。

        优先返回结构化数据（JSON），因为信息最完整；
        若同时有文本，一并附上便于模型理解。
        """
        parts: list[str] = []

        if self.is_error:
            message = self.error_message or self.text or "MCP 工具返回了错误"
            return f"MCP 工具调用失败：{message}"

        if self.structured is not None:
            import json

            parts.append(json.dumps(self.structured, ensure_ascii=False, indent=2))
            if self.text and self.text.strip() and self.text.strip() not in parts[0]:
                parts.append("")
                parts.append("说明：")
                parts.append(self.text)
        elif self.text.strip():
            parts.append(self.text)

        return "\n".join(parts) if parts else "(MCP 工具没有返回内容)"


class _LoopThread:
    """在后台线程里运行一个 asyncio 事件循环。"""

    def __init__(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._run, name="mcp-client-loop", daemon=True
        )
        self._thread.start()

    def _run(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        return self._loop

    def run(self, coro, timeout: float | None = None):
        """把协程提交到后台循环并同步等待结果。"""
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout)

    def stop(self) -> None:
        if self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=5)


class McpServerHandle:
    """单个 MCP Server 的长连接句柄。

    连接在后台循环里保持，主线程通过 run() 发起调用。
    """

    def __init__(self, config: McpServerConfig, loop_thread: _LoopThread, connect_timeout: float) -> None:
        self.config = config
        self._loop_thread = loop_thread
        self._connect_timeout = connect_timeout
        self._client = None
        self._exit_stack = None

    @property
    def name(self) -> str:
        return self.config.name

    # ---------------------------------------------------------------- 连接
    async def _open(self) -> None:
        from contextlib import AsyncExitStack

        from mcp import Client

        stack = AsyncExitStack()
        try:
            ctx = Client(self._build_target())
            client = await stack.enter_async_context(ctx)
        except Exception as exc:  # noqa: BLE001 连接失败统一包装
            await stack.aclose()
            raise McpConnectionError(self._friendly_exc(exc)) from exc

        self._client = client
        self._exit_stack = stack

    def _build_target(self):
        """按传输类型构造 Client 的连接目标。

        - HTTP  ：直接传 URL 字符串
        - stdio ：传 StdioServerParameters，由 SDK 负责拉起子进程
        """
        if not self.config.is_stdio:
            return self.config.url

        from mcp.client.stdio import StdioServerParameters

        if not self.config.command:
            raise McpConnectionError("stdio 配置缺少 command")

        kwargs: dict = {
            "command": self.config.command,
            "args": list(self.config.args),
        }
        if self.config.env:
            kwargs["env"] = dict(self.config.env)
        if self.config.cwd:
            kwargs["cwd"] = self.config.cwd

        try:
            return StdioServerParameters(**kwargs)
        except TypeError:
            # 兼容不接受 cwd 的旧版本 SDK
            kwargs.pop("cwd", None)
            return StdioServerParameters(**kwargs)

    async def _close(self) -> None:
        if self._exit_stack is not None:
            try:
                await self._exit_stack.aclose()
            except Exception:  # noqa: BLE001 关闭异常忽略
                pass
        self._client = None
        self._exit_stack = None

    @staticmethod
    def _friendly_exc(exc: BaseException) -> str:
        """把 SDK 抛出的异常翻译成可读信息。

        anyio 的 TaskGroup 会把真实原因包在 ExceptionGroup 里，
        这里递归取出最内层原因，否则只能看到
        「unhandled errors in a TaskGroup」这种没有信息量的话。
        """
        cause = _unwrap(exc)
        text = str(cause).strip() or type(cause).__name__
        lowered = text.lower()
        if "refused" in lowered or "10061" in text:
            return f"连接被拒绝（{text}），请确认 MCP Server 已启动且 URL 正确"
        if "timed out" in lowered or "timeout" in lowered:
            return f"连接超时（{text}）"
        if "404" in text:
            return f"URL 路径不正确（{text}）"
        # stdio 子进程相关
        if isinstance(cause, FileNotFoundError):
            return f"找不到可执行文件（{text}），请检查 command 是否正确、是否在 PATH 中"
        if isinstance(cause, PermissionError):
            return f"无权执行该命令（{text}）"
        if "no such file" in lowered or "not found" in lowered:
            return f"找不到命令或程序（{text}）"
        if "connect" in lowered:
            return f"无法连接（{text}）"
        return f"{type(cause).__name__}: {text}"

    # ---------------------------------------------------------------- 同步 API
    def connect(self) -> None:
        try:
            self._loop_thread.run(self._open(), timeout=self._connect_timeout)
        except McpConnectionError:
            raise
        except TimeoutError as exc:
            raise McpConnectionError(
                f"连接超时（超过 {self._connect_timeout:.0f} 秒）"
            ) from exc
        except Exception as exc:  # noqa: BLE001
            raise McpConnectionError(self._friendly_exc(exc)) from exc

    def list_tools(self) -> list[McpToolInfo]:
        if self._client is None:
            raise McpConnectionError("尚未连接")
        try:
            result = self._loop_thread.run(self._client.list_tools(), timeout=self._connect_timeout)
        except Exception as exc:  # noqa: BLE001
            raise McpConnectionError(f"list_tools 失败：{self._friendly_exc(exc)}") from exc

        tools: list[McpToolInfo] = []
        for tool in getattr(result, "tools", []) or []:
            tools.append(
                McpToolInfo(
                    server=self.name,
                    name=str(tool.name),
                    description=str(tool.description or ""),
                    input_schema=dict(tool.input_schema or {}),
                )
            )
        return tools

    def call_tool(self, tool_name: str, arguments: dict[str, Any], timeout: float) -> McpCallResult:
        if self._client is None:
            raise McpConnectionError("尚未连接")

        async def _invoke():
            return await self._client.call_tool(tool_name, arguments)

        try:
            result = self._loop_thread.run(_invoke(), timeout=timeout)
        except TimeoutError as exc:
            raise McpCallError(f"调用超时（超过 {timeout:.0f} 秒）") from exc
        except Exception as exc:  # noqa: BLE001
            raise McpCallError(self._friendly_exc(exc)) from exc

        return _to_call_result(result)

    def close(self) -> None:
        try:
            self._loop_thread.run(self._close(), timeout=5)
        except Exception:  # noqa: BLE001
            pass


def _unwrap(exc: BaseException, depth: int = 0) -> BaseException:
    """递归取出 ExceptionGroup 里最内层的真实异常。"""
    if depth > 8:
        return exc
    sub = getattr(exc, "exceptions", None)
    if isinstance(sub, (list, tuple)) and sub:
        return _unwrap(sub[0], depth + 1)
    if exc.__cause__ is not None:
        return _unwrap(exc.__cause__, depth + 1)
    return exc


def _to_call_result(result: Any) -> McpCallResult:
    """把 SDK 的 CallToolResult 转成统一的 McpCallResult。"""
    texts: list[str] = []
    for item in getattr(result, "content", None) or []:
        text = getattr(item, "text", None)
        if text:
            texts.append(str(text))

    structured = getattr(result, "structured_content", None)
    if not isinstance(structured, dict):
        structured = None

    is_error = bool(getattr(result, "is_error", False))
    error_message = ""

    if is_error:
        error_message = "\n".join(texts).strip()
        if structured and "error" in structured:
            err = structured["error"]
            if isinstance(err, dict):
                error_message = (
                    f"{err.get('message') or err.get('code') or error_message}"
                )
            elif err:
                error_message = str(err)

    return McpCallResult(
        text="\n".join(texts).strip(),
        structured=structured,
        is_error=is_error,
        error_message=error_message,
    )


__all__ = [
    "McpCallError",
    "McpCallResult",
    "McpConnectionError",
    "McpServerHandle",
    "McpToolInfo",
    "_LoopThread",
]
