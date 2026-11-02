"""MCP 客户端子系统。

读取项目根目录的 .mcp.json，连接外部 MCP Server，
把其工具动态注册进 wAgent 的工具集合。

    core/mcp/config.py    .mcp.json 解析
    core/mcp/client.py    后台线程事件循环 + MCP Server 长连接
    core/mcp/manager.py   连接管理、工具发现、名称冲突处理
    core/mcp/tools.py     MCP 工具 → 本地 Tool 的包装
"""

from .client import McpCallError, McpCallResult, McpConnectionError, McpToolInfo
from .config import McpConfigError, McpConfigIssue, McpServerConfig, load_mcp_config
from .manager import McpManager, McpServerStatus, McpToolRoute, build_mcp_manager
from .prompt import build_mcp_prompt
from .tools import McpToolWrapper, build_mcp_tools

__all__ = [
    "McpCallError",
    "McpCallResult",
    "McpConfigError",
    "McpConfigIssue",
    "McpConnectionError",
    "McpManager",
    "McpServerConfig",
    "McpServerStatus",
    "McpToolInfo",
    "McpToolRoute",
    "McpToolWrapper",
    "build_mcp_manager",
    "build_mcp_prompt",
    "build_mcp_tools",
    "load_mcp_config",
]
