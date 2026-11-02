"""main.py 的启动配置测试。

重点：每轮模型调用上限为 20 次，且其余行为保持不变。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from core.agent import Agent  # noqa: E402
from core.config import AgentSettings  # noqa: E402
from core.llm.client import LLMClient, StreamChunk, ToolCallDelta  # noqa: E402
from core.tools.base import Tool, ToolRegistry  # noqa: E402


def load_main():
    spec = importlib.util.spec_from_file_location("wagent_main", BASE / "main.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


main_module = load_main()


# ---------------------------------------------------------------- 常量
def test_total_calls_constant_is_20():
    assert main_module.MAX_MODEL_CALLS_PER_ROUND == 20


def test_tool_rounds_is_total_minus_one():
    """引擎按 max_tool_rounds + 1 循环，所以传入值应为 19。"""
    assert main_module.MAX_TOOL_ROUNDS == 19


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


def test_actual_model_calls_capped_at_20():
    client = LoopClient()
    registry = ToolRegistry()
    registry.register(NoopTool())

    agent = Agent(
        AgentSettings(max_tool_rounds=main_module.MAX_TOOL_ROUNDS), client, registry
    )
    with pytest.raises(RuntimeError, match="工具调用次数过多"):
        list(agent.stream_reply("无限调用"))

    assert client.calls == 20


def test_build_agent_accepts_round_override():
    from core import build_agent

    agent = build_agent(max_tool_rounds=main_module.MAX_TOOL_ROUNDS)
    assert agent._settings.max_tool_rounds == 19


# ---------------------------------------------------------------- 其它不变
def test_default_setting_untouched():
    """不传参数时仍用默认值，避免影响其他调用方与测试。"""
    from core import build_agent

    agent = build_agent()
    assert agent._settings.max_tool_rounds == 5


def test_tui_reports_total_calls_not_tool_rounds():
    """侧栏显示的是总调用次数（20），不是 19。"""
    import asyncio

    from core import build_agent
    from tui.app import AgentTUI

    async def run():
        agent = build_agent(max_tool_rounds=main_module.MAX_TOOL_ROUNDS)
        app = AgentTUI(agent)
        async with app.run_test(size=(100, 28)) as pilot:
            await pilot.pause()
            text = str(app.query_one("#session-info").render())
            assert "20 次模型调用/轮" in text
            assert "19 次模型调用/轮" not in text

    asyncio.run(run())


def test_system_prompt_and_tools_unchanged():
    """改上限不影响工具集与 System Prompt。"""
    from core import build_agent

    a = build_agent(max_tool_rounds=main_module.MAX_TOOL_ROUNDS)
    b = build_agent()
    assert a.tool_names == b.tool_names
    assert a.system_prompt == b.system_prompt
