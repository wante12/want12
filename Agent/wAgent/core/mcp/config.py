"""`.mcp.json` 配置的解析。

文件位置：**项目根**（程序启动时的工作目录），不是源代码目录。
格式兼容 Claude Desktop / MCP 生态的常见写法，支持两种传输：

    1) Streamable HTTP（远程 URL）：
       {
         "mcpServers": {
           "pet-hospital": {
             "type": "streamableHttp",
             "url": "http://127.0.0.1:8090/mcp"
           }
         }
       }

    2) stdio（本地子进程，通过标准输入输出通信）：
       {
         "mcpServers": {
           "bazi": {
             "command": "npx",
             "args": ["-y", "bazi-mcp"],
             "env": {"NODE_ENV": "production"}
           }
         }
       }

未显式声明 `type` 时按字段推断：
    有 `command` → stdio；有 `url` → streamableHttp。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: 配置文件名
DEFAULT_FILENAME = ".mcp.json"
#: 支持的传输类型别名
HTTP_TYPES = {"streamablehttp", "streamable-http", "http", "sse", None, ""}
STDIO_TYPES = {"stdio"}
#: 全部允许的类型
ALL_TYPES = HTTP_TYPES | STDIO_TYPES

TRANSPORT_HTTP = "http"
TRANSPORT_STDIO = "stdio"


class McpConfigError(Exception):
    """配置文件缺失、格式错误或内容非法。"""


@dataclass(frozen=True)
class McpServerConfig:
    """单个 MCP Server 的连接信息。

    两种传输共用一个结构，靠 `transport` 区分：
    - http  ：使用 url / headers
    - stdio ：使用 command / args / env / cwd
    """

    name: str
    url: str = ""
    #: 额外的 HTTP 头（如 Authorization），便于连需要鉴权的服务器
    headers: dict[str, str] = field(default_factory=dict)
    #: http 或 stdio
    transport: str = TRANSPORT_HTTP
    #: stdio：可执行文件
    command: str = ""
    #: stdio：参数列表
    args: tuple[str, ...] = ()
    #: stdio：环境变量（在继承当前环境的基础上追加）
    env: dict[str, str] = field(default_factory=dict)
    #: stdio：工作目录
    cwd: str | None = None

    @property
    def is_stdio(self) -> bool:
        return self.transport == TRANSPORT_STDIO

    def describe(self) -> str:
        """给界面/日志看的一行描述。"""
        if self.is_stdio:
            parts = " ".join([self.command, *self.args]).strip()
            return f"stdio: {parts}"
        return f"http: {self.url}"

    def __repr__(self) -> str:
        return f"McpServerConfig(name={self.name!r}, {self.describe()!r})"


@dataclass
class McpConfigIssue:
    """一条配置问题，用于向用户报告而不阻断启动。"""

    server: str
    reason: str

    def __str__(self) -> str:
        return f"{self.server}: {self.reason}"


def config_path(project_root: Path | str | None = None, filename: str = DEFAULT_FILENAME) -> Path:
    root = Path(project_root) if project_root else Path.cwd()
    return root / filename


def load_mcp_config(
    project_root: Path | str | None = None,
    filename: str = DEFAULT_FILENAME,
) -> tuple[list[McpServerConfig], list[McpConfigIssue]]:
    """读取并校验 .mcp.json。

    返回 (可用服务器列表, 问题列表)。
    文件不存在时返回空结果——没有 MCP 也能正常使用 wAgent。
    文件存在但格式错误时抛 McpConfigError（这种情况下静默忽略会让用户困惑）。
    """
    path = config_path(project_root, filename)
    if not path.is_file():
        return [], []

    try:
        # utf-8-sig 兼容带 BOM 的文件（Windows 记事本 / PowerShell 常见）
        raw = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise McpConfigError(f"无法读取 {path}：{exc}") from exc

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise McpConfigError(f"{path} 不是合法 JSON：{exc}") from exc

    if not isinstance(data, dict):
        raise McpConfigError(f"{path} 顶层必须是 JSON 对象")

    servers_raw = data.get("mcpServers")
    if servers_raw is None:
        raise McpConfigError(f"{path} 缺少 mcpServers 字段")
    if not isinstance(servers_raw, dict):
        raise McpConfigError(f"{path} 的 mcpServers 必须是对象")

    servers: list[McpServerConfig] = []
    issues: list[McpConfigIssue] = []

    for name, entry in servers_raw.items():
        if not isinstance(entry, dict):
            issues.append(McpConfigIssue(name, "配置项必须是对象"))
            continue

        raw_type = entry.get("type", entry.get("transport"))
        transport = raw_type.lower() if isinstance(raw_type, str) else raw_type

        # 未声明 type 时按字段推断：有 command 走 stdio，否则走 http
        if transport in (None, ""):
            transport = TRANSPORT_STDIO if entry.get("command") else TRANSPORT_HTTP

        if transport not in ALL_TYPES:
            issues.append(
                McpConfigIssue(
                    name,
                    f"不支持的传输类型「{raw_type}」，"
                    "可选 streamableHttp 或 stdio",
                )
            )
            continue

        if transport == TRANSPORT_STDIO:
            server, issue = _parse_stdio(name, entry)
        else:
            server, issue = _parse_http(name, entry)

        if issue is not None:
            issues.append(issue)
            continue
        servers.append(server)

    return servers, issues


def _parse_http(
    name: str, entry: dict[str, Any]
) -> tuple[McpServerConfig, McpConfigIssue | None]:
    """解析 Streamable HTTP 配置。"""
    url = str(entry.get("url") or "").strip()
    if not url:
        return _empty(), McpConfigIssue(name, "缺少 url 字段")
    if not url.lower().startswith(("http://", "https://")):
        return _empty(), McpConfigIssue(
            name, f"url 必须以 http:// 或 https:// 开头：{url}"
        )

    headers_raw = entry.get("headers") or {}
    headers: dict[str, str] = {}
    if isinstance(headers_raw, dict):
        headers = {str(k): str(v) for k, v in headers_raw.items()}

    return (
        McpServerConfig(
            name=str(name),
            url=url,
            headers=headers,
            transport=TRANSPORT_HTTP,
        ),
        None,
    )


def _parse_stdio(
    name: str, entry: dict[str, Any]
) -> tuple[McpServerConfig, McpConfigIssue | None]:
    """解析 stdio（本地子进程）配置。"""
    command = str(entry.get("command") or "").strip()
    if not command:
        return _empty(), McpConfigIssue(
            name, "stdio 传输缺少 command 字段"
        )

    args_raw = entry.get("args") or []
    if isinstance(args_raw, str):
        args_raw = [args_raw]
    if not isinstance(args_raw, (list, tuple)):
        return _empty(), McpConfigIssue(name, "args 必须是数组")
    args = tuple(str(a) for a in args_raw)

    env_raw = entry.get("env") or {}
    env: dict[str, str] = {}
    if isinstance(env_raw, dict):
        env = {str(k): str(v) for k, v in env_raw.items()}

    cwd_raw = entry.get("cwd")
    cwd = str(cwd_raw).strip() if cwd_raw else None

    return (
        McpServerConfig(
            name=str(name),
            transport=TRANSPORT_STDIO,
            command=command,
            args=args,
            env=env,
            cwd=cwd,
        ),
        None,
    )


def _empty() -> McpServerConfig:
    return McpServerConfig(name="")


__all__ = [
    "ALL_TYPES",
    "DEFAULT_FILENAME",
    "HTTP_TYPES",
    "STDIO_TYPES",
    "TRANSPORT_HTTP",
    "TRANSPORT_STDIO",
    "McpConfigError",
    "McpConfigIssue",
    "McpServerConfig",
    "config_path",
    "load_mcp_config",
]
