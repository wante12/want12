"""core 层测试：不依赖网络、不依赖 UI。

用假 LLM 客户端验证 Agent 的编排逻辑。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from core.agent import Agent  # noqa: E402
from core.config import AgentSettings, ConfigError, AppConfig  # noqa: E402
from core.events import EventType  # noqa: E402
from core.llm.client import LLMClient, StreamChunk, ToolCallDelta  # noqa: E402
from core.tools.base import Tool, ToolRegistry  # noqa: E402
from core.tools.builtin import GetDateTool  # noqa: E402


class ScriptedClient(LLMClient):
    """按预设脚本依次返回流式片段。"""

    def __init__(self, script: list[list[StreamChunk]]) -> None:
        self._script = script
        self.calls: list[list[dict]] = []

    def stream(self, messages, tools=None):
        self.calls.append(list(messages))
        return iter(self._script.pop(0))


class EchoTool(Tool):
    name = "echo"
    description = "原样返回输入"
    parameters = {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
        "additionalProperties": False,
    }

    def run(self, text: str) -> str:
        return f"echo:{text}"


def make_agent(script) -> Agent:
    return Agent(AgentSettings(), ScriptedClient(script), ToolRegistry())


# ---------------------------------------------------------------- 配置
def test_config_missing_file(tmp_path):
    with pytest.raises(ConfigError):
        AppConfig.load(tmp_path / "nope.ini")


def test_config_missing_field(tmp_path):
    p = tmp_path / "config.ini"
    p.write_text("[llm]\nbase_url=x\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        AppConfig.load(p)


def test_config_ok(tmp_path):
    p = tmp_path / "config.ini"
    p.write_text(
        "[llm]\nbase_url=https://x/v1\napi_key=sk-1\nmodel=m\n", encoding="utf-8"
    )
    cfg = AppConfig.load(p)
    assert cfg.llm.model == "m"
    assert "sk-1" not in repr(cfg.llm)  # 密钥不出现在 repr


# ---------------------------------------------------------------- 工具
def test_registry_unknown_tool():
    assert ToolRegistry().execute("nope", "{}").startswith("未知工具")


def test_registry_bad_json():
    reg = ToolRegistry()
    reg.register(EchoTool())
    assert "解析失败" in reg.execute("echo", "{bad")


def test_registry_handles_tool_exception():
    class Boom(Tool):
        name = "boom"
        description = "抛异常"

        def run(self) -> str:
            raise ValueError("炸了")

    reg = ToolRegistry()
    reg.register(Boom())
    assert "执行失败" in reg.execute("boom", "{}")


def test_get_date_returns_text():
    assert GetDateTool().run().strip()


# ---------------------------------------------------------------- Agent
def test_plain_answer_no_tool():
    client_script = [[StreamChunk(text="你"), StreamChunk(text="好")]]
    agent = make_agent(client_script)
    events = list(agent.stream_reply("hi"))

    kinds = [e.type for e in events]
    assert kinds[0] is EventType.ROUND_STARTED
    assert kinds[-1] is EventType.ROUND_FINISHED
    text = "".join(e.text for e in events if e.type is EventType.TEXT_DELTA)
    assert text == "你好"
    assert agent.history[-1]["role"] == "assistant"


def test_tool_call_round_trip():
    script = [
        # 第一次：模型请求调用工具
        [StreamChunk(tool_calls=[ToolCallDelta(index=0, id="c1", name="echo",
                                               arguments='{"text":"x"}')])],
        # 第二次：拿到工具结果后给出回答
        [StreamChunk(text="完成")],
    ]
    agent = make_agent(script)
    agent._registry.register(EchoTool())

    events = list(agent.stream_reply("调用工具"))
    kinds = [e.type for e in events]

    assert EventType.TOOL_CALL_STARTED in kinds
    assert EventType.TOOL_CALL_FINISHED in kinds
    finished = next(e for e in events if e.type is EventType.TOOL_CALL_FINISHED)
    assert finished.payload["result"] == "echo:x"

    roles = [m["role"] for m in agent.history]
    assert "tool" in roles


def test_rollback_on_error():
    class Bad(LLMClient):
        def stream(self, messages, tools=None):
            raise RuntimeError("网络挂了")

    agent = Agent(AgentSettings(), Bad(), ToolRegistry())
    with pytest.raises(RuntimeError):
        list(agent.stream_reply("hi"))
    # 本轮消息必须回滚，只剩 system
    assert [m["role"] for m in agent.history] == ["system"]


def test_reset_clears_history():
    agent = make_agent([[StreamChunk(text="ok")]])
    list(agent.stream_reply("hi"))
    assert len(agent.history) > 1
    agent.reset()
    assert [m["role"] for m in agent.history] == ["system"]
