"""`.mcp.json` 配置的解析。

文件位置：**项目根**（程序启动时的工作目录），不是源代码目录。
格式兼容 Claude Desktop / MCP 生态的常见写法：

    {
      "mcpServers": {
        "pet-hospital": {
          "type": "streamableHttp",
          "url": "http://127.0.0.1:8080/mcp"
        }
      }
    }

本阶段只支持 Streamable HTTP（远程 URL）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: 配置文件名
DEFAULT_FILENAME = ".mcp.json"
#: 支持的传输类型别名（均为 Streamable HTTP）
HTTP_TYPES = {"streamablehttp", "streamable-http", "http", "sse", None, ""}


class McpConfigError(Exception):
    """配置文件缺失、格式错误或内容非法。"""


@dataclass(frozen=True)
class McpServerConfig:
    """单个 MCP Server 的连接信息。"""

    name: str
    url: str
    #: 额外的 HTTP 头（如 Authorization），便于连需要鉴权的服务器
    headers: dict[str, str] = field(default_factory=dict)

    def __repr__(self) -> str:
        return f"McpServerConfig(name={self.name!r}, url={self.url!r})"


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

        transport = entry.get("type", entry.get("transport"))
        if isinstance(transport, str) and transport.lower() not in HTTP_TYPES:
            issues.append(
                McpConfigIssue(
                    name,
                    f"不支持的传输类型「{transport}」，本版本仅支持 streamableHttp",
                )
            )
            continue

        url = str(entry.get("url") or "").strip()
        if not url:
            issues.append(McpConfigIssue(name, "缺少 url 字段"))
            continue
        if not url.lower().startswith(("http://", "https://")):
            issues.append(McpConfigIssue(name, f"url 必须以 http:// 或 https:// 开头：{url}"))
            continue

        headers_raw = entry.get("headers") or {}
        headers: dict[str, str] = {}
        if isinstance(headers_raw, dict):
            headers = {str(k): str(v) for k, v in headers_raw.items()}

        servers.append(McpServerConfig(name=str(name), url=url, headers=headers))

    return servers, issues


__all__ = [
    "DEFAULT_FILENAME",
    "McpConfigError",
    "McpConfigIssue",
    "McpServerConfig",
    "config_path",
    "load_mcp_config",
]
