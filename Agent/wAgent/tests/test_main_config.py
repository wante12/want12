"""main.py 与配置的启动测试。

重点：每轮模型调用上限为 20 次，由 config.ini 的 [agent] 段控制。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from core.agent import Agent  # noqa: E402
from core.config import AgentSettings, AppConfig, ensure_config_file  # noqa: E402
from core.llm.client import LLMClient, StreamChunk, ToolCallDelta  # noqa: E402
from core.tools.base import Tool, ToolRegistry  # noqa: E402


def load_main():
    spec = importlib.util.spec_from_file_location("wagent_main", BASE / "main.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


main_module = load_main()


# ---------------------------------------------------------------- 配置默认值
def test_default_max_model_calls_is_200():
    assert AgentSettings().max_model_calls_per_round == 200


def test_default_tool_rounds_is_total_minus_one():
    """引擎按 max_tool_rounds + 1 循环，所以默认值应为 199。"""
    assert AgentSettings().max_tool_rounds == 199


def test_default_rounds_are_consistent():
    """两个值必须保持「总次数 = 工具轮数 + 1」的关系。"""
    settings = AgentSettings()
    assert settings.max_tool_rounds + 1 == settings.max_model_calls_per_round


def test_config_file_provides_tool_rounds():
    """config.ini 提供 max_tool_rounds，而不是硬编码。"""
    cfg = AppConfig.load(BASE / "config.ini")
    assert cfg.agent.max_tool_rounds == 199
    assert cfg.agent.max_model_calls_per_round == 200


# ---------------------------------------------------------------- 生效验证
class LoopClient(LLMClient):
    """每次都请求工具，用来撞上限。"""

    def __init__(self) -> None:
        self.calls = 0

    def stream(self, messages, tools=None):
        self.calls += 1
        return iter(
            [
                StreamChunk(
                    tool_calls=[
                        ToolCallDelta(
                            index=0, id=f"c{self.calls}", name="noop", arguments="{}"
                        )
                    ]
                )
            ]
        )


class NoopTool(Tool):
    name = "noop"
    description = "空工具"

    def run(self) -> str:
        return "ok"


def test_actual_model_calls_match_configured_limit():
    """上限生效：用小值验证，避免测试真的跑 200 次。

    引擎循环 max_tool_rounds + 1 次，因此模型调用次数应等于该值。
    """
    client = LoopClient()
    registry = ToolRegistry()
    registry.register(NoopTool())

    agent = Agent(AgentSettings(max_tool_rounds=4), client, registry)
    with pytest.raises(RuntimeError, match="工具调用次数过多"):
        list(agent.stream_reply("无限调用"))

    assert client.calls == 5        # 4 + 1


def test_default_limit_is_200_calls():
    """默认配置下调用次数上限就是 200（不实际执行，只验算）。"""
    settings = AgentSettings()
    engine_loops = settings.max_tool_rounds + 1
    assert engine_loops == settings.max_model_calls_per_round == 200


def test_build_agent_accepts_round_override():
    from core import build_agent

    agent = build_agent(max_tool_rounds=9)
    assert agent._settings.max_tool_rounds == 9


# ---------------------------------------------------------------- 其它不变
def test_default_setting_uses_config():
    """build_agent 不传参数时用配置里的值。"""
    from core import build_agent

    cfg = AppConfig.load(BASE / "config.ini")
    agent = build_agent()
    assert agent._settings.max_tool_rounds == cfg.agent.max_tool_rounds


def test_tui_reports_total_calls_not_tool_rounds():
    """侧栏显示的是总调用次数，不是工具轮数。"""
    import asyncio

    from core import build_agent
    from tui.app import AgentTUI

    async def run():
        agent = build_agent(max_tool_rounds=9)
        app = AgentTUI(agent, mcp_async=False)
        async with app.run_test(size=(100, 28)) as pilot:
            await pilot.pause()
            text = str(app.query_one("#session-info").render())
            assert "10 次模型调用/轮" in text
            assert "9 次模型调用/轮" not in text

    asyncio.run(run())


def test_system_prompt_and_tools_unchanged():
    """改上限不影响工具集与 System Prompt。"""
    from core import build_agent

    a = build_agent(max_tool_rounds=9)
    b = build_agent()
    assert a.tool_names == b.tool_names
    assert a.system_prompt == b.system_prompt


# ---------------------------------------------------------------- 配置生成
def test_ensure_config_file_creates_template(tmp_path):
    path = tmp_path / "config.ini"
    assert not path.exists()

    result, created = ensure_config_file(path)
    assert created is True
    assert result.is_file()

    text = result.read_text(encoding="utf-8")
    for section in ("[llm]", "[agent]", "[context]", "[session]", "[mcp]", "[ui]"):
        assert section in text


def test_generated_config_loads(tmp_path):
    path, _ = ensure_config_file(tmp_path / "config.ini")
    cfg = AppConfig.load(path)
    assert cfg.llm.model
    assert cfg.agent.max_tool_rounds == 199
    assert cfg.agent.max_model_calls_per_round == 200


def test_ensure_config_file_idempotent(tmp_path):
    path = tmp_path / "config.ini"
    ensure_config_file(path)
    _, created = ensure_config_file(path)
    assert created is False


def test_mock_config_detected(tmp_path):
    from core.config import is_mock_config

    path, _ = ensure_config_file(tmp_path / "config.ini")
    assert is_mock_config(AppConfig.load(path)) is True
