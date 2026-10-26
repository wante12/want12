"""应用装配（Composition Root）。

任何 UI 层都通过 build_agent() 拿到配置好的 Agent，
不需要了解 OpenAI、工具注册等细节。
这是替换或新增前端时唯一需要接触的 core 入口。
"""

from __future__ import annotations

from pathlib import Path

from .agent.engine import Agent
from .config import AppConfig, CliSettings, FetchSettings, FsSettings, SearchSettings
from .llm.client import LLMClient, OpenAICompatClient
from .tools.base import Tool, ToolRegistry
from .tools.builtin import GetDateTool
from .tools.cli import RunCliTool
from .tools.fetch import FetchWebTool
from .tools.filesystem import build_fs_tools
from .tools.search import SearchWebTool

DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "config.ini"


def build_registry(
    *extra_tools: Tool,
    search: SearchSettings | None = None,
    fetch: FetchSettings | None = None,
    cli: CliSettings | None = None,
    fs: FsSettings | None = None,
) -> ToolRegistry:
    """构造默认工具集，可追加自定义工具。

    search 为空时仍注册 searchWeb，但调用时会返回「未配置」的提示，
    这样模型能明确知道缺什么，而不是工具凭空消失。
    """
    registry = ToolRegistry()
    registry.register(GetDateTool())
    registry.register(SearchWebTool(search or SearchSettings()))
    registry.register(FetchWebTool(fetch or FetchSettings()))
    registry.register(RunCliTool(cli or CliSettings()))
    for tool in build_fs_tools(fs):
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
) -> Agent:
    """组装一个可用的 Agent。

    参数都可注入，便于测试时替换 LLM 客户端。
    """
    cfg = AppConfig.load(config_path or DEFAULT_CONFIG)
    return Agent(
        settings=cfg.agent,
        client=client or OpenAICompatClient(cfg.llm),
        registry=registry
        or build_registry(
            *extra_tools,
            search=cfg.search,
            fetch=cfg.fetch,
            cli=cfg.cli,
            fs=cfg.fs,
        ),
    )


__all__ = ["Agent", "AppConfig", "build_agent", "build_registry", "DEFAULT_CONFIG"]
