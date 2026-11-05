"""MCP 工具管理：连接、发现、注册与调用转发。

职责：
    1. 读取 .mcp.json，逐个连接 MCP Server（失败不阻断其他）
    2. 调用 list_tools() 发现工具
    3. 处理工具名冲突：必要时为暴露给 LLM 的名称加服务器名前缀
    4. 维护「暴露名 → (服务器, 原始工具名)」映射，转发调用
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .client import (
    McpCallError,
    McpConnectionError,
    McpServerHandle,
    McpToolInfo,
    _LoopThread,
)
from .config import McpConfigError, McpServerConfig, load_mcp_config


@dataclass
class McpToolRoute:
    """一个 MCP 工具的路由信息。"""

    exposed_name: str
    server: str
    original_name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)


@dataclass
class McpServerStatus:
    """单个服务器的连接结果，用于向用户汇报。"""

    name: str
    url: str
    connected: bool
    tool_count: int = 0
    error: str = ""

    def __str__(self) -> str:
        if self.connected:
            return f"{self.name}: 已连接（{self.tool_count} 个工具）"
        return f"{self.name}: 连接失败（{self.error}）"


def _sanitize(name: str) -> str:
    """把服务器名规范成可拼进工具名的形式。"""
    cleaned = "".join(ch if (ch.isalnum() or ch in "-_") else "_" for ch in name)
    return cleaned.strip("_-") or "mcp"


class McpManager:
    """管理所有 MCP Server 的生命周期与工具路由。"""

    def __init__(
        self,
        *,
        connect_timeout: float = 10.0,
        call_timeout: float = 60.0,
        prefix_mode: str = "auto",
        async_load: bool = False,
    ) -> None:
        self._connect_timeout = connect_timeout
        self._call_timeout = call_timeout
        self._prefix_mode = prefix_mode
        self._async_load = async_load

        self._loop_thread: _LoopThread | None = None
        self._handles: dict[str, McpServerHandle] = {}
        self._routes: dict[str, McpToolRoute] = {}
        self._statuses: list[McpServerStatus] = []
        self._issues: list[str] = []
        self._config_path: Path | None = None
        self._started = False
        #: 异步加载用：已读到的服务器配置
        self._servers: list[McpServerConfig] = []
        #: 异步加载用：边连边发布的工具（供 UI 增量刷新）
        self._live_discovered: list[McpToolInfo] = []
        #: 服务器状态变化时的回调
        self._tool_sink = None

    # ---------------------------------------------------------------- 属性
    @property
    def routes(self) -> list[McpToolRoute]:
        return list(self._routes.values())

    @property
    def statuses(self) -> list[McpServerStatus]:
        return list(self._statuses)

    @property
    def issues(self) -> list[str]:
        """配置层面的问题（url 非法、传输类型不支持等）。"""
        return list(self._issues)

    @property
    def config_path(self) -> Path | None:
        return self._config_path

    @property
    def async_load(self) -> bool:
        """是否为延迟连接模式（先读配置，稍后由调用方 connect_all）。"""
        return self._async_load

    @property
    def has_tools(self) -> bool:
        return bool(self._routes)

    def __len__(self) -> int:
        return len(self._routes)

    # ---------------------------------------------------------------- 启动
    def load_config(self, project_root: Path | str | None = None, filename: str = ".mcp.json") -> None:
        """只读取配置，不建立连接（供异步加载的第一步使用）。"""
        root = Path(project_root) if project_root else Path.cwd()
        self._config_path = root / filename
        self._servers: list[McpServerConfig] = []

        try:
            servers, issues = load_mcp_config(root, filename)
        except McpConfigError as exc:
            self._issues.append(str(exc))
            return

        self._issues.extend(str(i) for i in issues)
        self._servers = servers

    def connect_all(self) -> None:
        """按已读取的配置逐个连接并发现工具。失败只记录，不抛出。"""
        if not self._servers:
            return

        self._loop_thread = _LoopThread()
        discovered: list[McpToolInfo] = []

        for server in self._servers:
            handle = McpServerHandle(server, self._loop_thread, self._connect_timeout)
            try:
                handle.connect()
                tools = handle.list_tools()
            except McpConnectionError as exc:
                self._statuses.append(
                    McpServerStatus(server.name, server.url, False, error=str(exc))
                )
                handle.close()
                self._on_server_done()
                continue
            except Exception as exc:  # noqa: BLE001 兜底，绝不影响启动
                self._statuses.append(
                    McpServerStatus(server.name, server.url, False, error=f"{type(exc).__name__}: {exc}")
                )
                handle.close()
                self._on_server_done()
                continue

            self._handles[server.name] = handle
            self._statuses.append(
                McpServerStatus(server.name, server.url, True, tool_count=len(tools))
            )
            discovered.extend(tools)
            self._publish_tools(tools)
            self._on_server_done()

        self._build_routes(discovered)

    def start(self, project_root: Path | str | None = None, filename: str = ".mcp.json") -> None:
        """同步完成：读配置 + 连接全部服务器。"""
        if self._started:
            return
        self._started = True
        self._live_discovered = []
        self.load_config(project_root, filename)
        self.connect_all()

    # ---------------------------------------------------------------- 异步钩子
    def set_tool_sink(self, sink) -> None:
        """注册回调：每发现一个新工具或服务器状态变化时被调用。

        TUI 用它动态刷新侧栏与工具集，无需重启。
        """
        self._tool_sink = sink

    def _on_server_done(self) -> None:
        sink = getattr(self, "_tool_sink", None)
        if callable(sink):
            try:
                sink()
            except Exception:  # noqa: BLE001 回调异常不影响连接
                pass

    def _publish_tools(self, tools: list[McpToolInfo]) -> None:
        live = getattr(self, "_live_discovered", None)
        if live is not None:
            live.extend(tools)

    def _build_routes(self, tools: list[McpToolInfo]) -> None:
        """分配暴露给 LLM 的工具名，避免跨服务器冲突。"""
        counts: dict[str, int] = {}
        for tool in tools:
            counts[tool.name] = counts.get(tool.name, 0) + 1

        for tool in tools:
            name = tool.name
            needs_prefix = (
                self._prefix_mode == "always"
                or (self._prefix_mode == "auto" and counts.get(name, 0) > 1)
            )
            exposed = f"{_sanitize(tool.server)}__{name}" if needs_prefix else name
            # 极端情况下前缀后仍冲突，追加序号
            base, suffix = exposed, 1
            while exposed in self._routes:
                suffix += 1
                exposed = f"{base}_{suffix}"

            self._routes[exposed] = McpToolRoute(
                exposed_name=exposed,
                server=tool.server,
                original_name=name,
                description=tool.description,
                input_schema=tool.input_schema,
            )

    # ---------------------------------------------------------------- 调用
    def call(self, exposed_name: str, arguments: dict[str, Any]) -> str:
        """按暴露名转发调用，返回给 LLM 的文本。

        任何异常都转成可读文本，不向 Agent 循环抛出。
        """
        route = self._routes.get(exposed_name)
        if route is None:
            return f"MCP 工具调用失败：未找到工具「{exposed_name}」"

        handle = self._handles.get(route.server)
        if handle is None:
            return f"MCP 工具调用失败：服务器「{route.server}」未连接"

        try:
            result = handle.call_tool(route.original_name, arguments or {}, self._call_timeout)
        except McpCallError as exc:
            return f"MCP 工具调用失败（{route.server}/{route.original_name}）：{exc}"
        except Exception as exc:  # noqa: BLE001
            return f"MCP 工具调用失败（{route.server}/{route.original_name}）：{type(exc).__name__}: {exc}"

        return result.render()

    # ---------------------------------------------------------------- 关闭
    def close(self) -> None:
        for handle in self._handles.values():
            handle.close()
        self._handles.clear()
        if self._loop_thread is not None:
            self._loop_thread.stop()
            self._loop_thread = None

    # ---------------------------------------------------------------- 展示
    def summary(self) -> str:
        """给 UI 的一行摘要。"""
        if not self._statuses and not self._issues:
            return "未配置 MCP Server"
        ok = [s for s in self._statuses if s.connected]
        return f"{len(ok)}/{len(self._statuses)} 个 MCP Server 已连接，{len(self._routes)} 个工具"


def build_mcp_manager(
    *,
    connect_timeout: float = 10.0,
    call_timeout: float = 60.0,
    prefix_mode: str = "auto",
    project_root: Path | str | None = None,
    filename: str = ".mcp.json",
    async_load: bool = False,
) -> McpManager:
    """构造一个 McpManager。

    async_load=False（默认）时立即连接完毕，供测试与脚本使用。
    async_load=True 时只读配置、不连接——由调用方（TUI）在后台线程
    执行 load_config() + connect_all()，实现「先进入界面，再连接」。
    """
    manager = McpManager(
        connect_timeout=connect_timeout,
        call_timeout=call_timeout,
        prefix_mode=prefix_mode,
        async_load=async_load,
    )
    if async_load:
        manager.load_config(project_root=project_root, filename=filename)
    else:
        manager.start(project_root=project_root, filename=filename)
    return manager


__all__ = [
    "McpManager",
    "McpServerStatus",
    "McpToolRoute",
    "build_mcp_manager",
]
