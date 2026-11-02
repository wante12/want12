"""应用装配（Composition Root）。

任何 UI 层都通过 build_agent() 拿到配置好的 Agent，
不需要了解 OpenAI、工具注册等细节。
这是替换或新增前端时唯一需要接触的 core 入口。
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

from .agent.engine import Agent
from .config import AppConfig, CliSettings, FetchSettings, FsSettings, SearchSettings
from .llm.client import LLMClient, OpenAICompatClient
from .mcp.manager import McpManager
from .mcp.prompt import build_mcp_prompt
from .mcp.tools import build_mcp_tools
from .skills.prompt import build_skills_prompt
from .skills.registry import SkillRegistry
from .tools.base import Tool, ToolRegistry
from .tools.builtin import GetDateTool
from .tools.cli import RunCliTool
from .tools.create_skill import build_create_skill_tool
from .tools.fetch import FetchWebTool
from .tools.filesystem import build_fs_tools
from .tools.search import SearchWebTool
from .tools.skill import build_load_skill_tool

DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "config.ini"


def build_registry(
    *extra_tools: Tool,
    search: SearchSettings | None = None,
    fetch: FetchSettings | None = None,
    cli: CliSettings | None = None,
    fs: FsSettings | None = None,
    skills: "SkillRegistry | None" = None,
    mcp: "McpManager | None" = None,
) -> ToolRegistry:
    """构造默认工具集，可追加自定义工具。

    search 为空时仍注册 searchWeb，但调用时会返回「未配置」的提示，
    这样模型能明确知道缺什么，而不是工具凭空消失。
    有技能时才注册 loadSkill，避免 Prompt 里的工具指向空实现。
    mcp 不为空时，把已发现的 MCP 工具一并注册，与本地工具平级。
    """
    registry = ToolRegistry()
    registry.register(GetDateTool())
    registry.register(SearchWebTool(search or SearchSettings()))
    registry.register(FetchWebTool(fetch or FetchSettings()))
    registry.register(RunCliTool(cli or CliSettings()))
    for tool in build_fs_tools(fs):
        registry.register(tool)

    load_skill_tool = build_load_skill_tool(skills)
    if load_skill_tool is not None:
        registry.register(load_skill_tool)

    # createSkill 始终注册：即使当前没有技能，也要能创建第一个
    registry.register(build_create_skill_tool(skills, tool_registry=registry))

    # MCP 工具：走同一条 Function Calling 通道
    for tool in build_mcp_tools(mcp):
        if tool.name in registry.names:
            # 与本地工具重名时跳过 MCP 版本，保证本地工具优先
            continue
        registry.register(tool)

    for tool in extra_tools:
        registry.register(tool)
    return registry


def build_agent(
    config_path: str | Path | None = None,
    *,
    client: LLMClient | None = None,
    registry: ToolRegistry | None = None,
    extra_tools: tuple[Tool, ...] = (),
    skills: "SkillRegistry | None" = None,
    mcp: "McpManager | None" = None,
    max_tool_rounds: int | None = None,
) -> Agent:
    """组装一个可用的 Agent。

    参数都可注入，便于测试时替换 LLM 客户端。
    skills 不为空时：
        1. 把技能清单注入 System Prompt
        2. 注册 loadSkill 工具供按需加载正文

    mcp 不为空时，其发现的工具会注册进同一个 ToolRegistry，
    与本地工具平级参与 Function Calling。

    max_tool_rounds 不为空时覆盖默认的工具轮次上限；
    引擎按「工具轮数 + 1」循环，因此模型调用总次数 = max_tool_rounds + 1。
    """
    cfg = AppConfig.load(config_path or DEFAULT_CONFIG)
    settings = cfg.agent
    if max_tool_rounds is not None:
        settings = dataclasses.replace(settings, max_tool_rounds=max_tool_rounds)

    return Agent(
        settings=settings,
        client=client or OpenAICompatClient(cfg.llm),
        registry=registry
        or build_registry(
            *extra_tools,
            search=cfg.search,
            fetch=cfg.fetch,
            cli=cfg.cli,
            fs=cfg.fs,
            skills=skills,
            mcp=mcp,
        ),
        system_prompt_extra=_compose_extra(skills, mcp),
    )


def _compose_extra(skills: "SkillRegistry | None", mcp: "McpManager | None") -> str:
    """拼出 System Prompt 的扩展段：技能清单 + MCP 工具说明。"""
    parts = []
    skills_part = build_skills_prompt(skills)
    if skills_part:
        parts.append(skills_part)
    mcp_part = build_mcp_prompt(mcp)
    if mcp_part:
        parts.append(mcp_part)
    return "\n\n".join(parts)


__all__ = ["Agent", "AppConfig", "build_agent", "build_registry", "DEFAULT_CONFIG"]
