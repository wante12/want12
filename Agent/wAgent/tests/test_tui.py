"""TUI 层测试：用 Textual 无头模式验证界面结构与交互。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from core.agent import Agent  # noqa: E402
from core.config import AgentSettings  # noqa: E402
from core.llm.client import LLMClient, StreamChunk, ToolCallDelta  # noqa: E402
from core.tools.base import Tool, ToolRegistry  # noqa: E402
from tui.app import AgentTUI  # noqa: E402
from tui.widgets.message import AssistantMessage, UserMessage  # noqa: E402
from tui.widgets.tool_card import ToolCard  # noqa: E402


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


class PlainClient(LLMClient):
    """直接返回一段文本。"""

    def stream(self, messages, tools=None):
        return iter([StreamChunk(text="你好"), StreamChunk(text="，世界")])


class ToolThenTextClient(LLMClient):
    """先请求工具调用，再基于结果作答。"""

    def __init__(self) -> None:
        self._n = 0

    def stream(self, messages, tools=None):
        self._n += 1
        if self._n == 1:
            return iter(
                [
                    StreamChunk(
                        tool_calls=[
                            ToolCallDelta(
                                index=0, id="c1", name="echo", arguments='{"text":"x"}'
                            )
                        ]
                    )
                ]
            )
        return iter([StreamChunk(text="完成")])


def make_agent(client: LLMClient | None = None) -> Agent:
    reg = ToolRegistry()
    reg.register(EchoTool())
    return Agent(AgentSettings(), client or PlainClient(), reg)


async def submit(app: AgentTUI, pilot, text: str) -> None:
    app.query_one("#input").value = text
    await pilot.press("enter")
    for _ in range(40):
        await pilot.pause(0.05)
        if not app._busy:
            break


# ---------------------------------------------------------------- 结构
async def test_layout_widgets_exist():
    app = AgentTUI(make_agent())
    async with app.run_test() as pilot:
        await pilot.pause()
        for selector in ("#topbar", "#chat", "#sidebar", "#input", "#statusbar"):
            assert app.query_one(selector) is not None


async def test_topbar_shows_tool_count():
    app = AgentTUI(make_agent())
    async with app.run_test() as pilot:
        await pilot.pause()
        topbar = str(app.query_one("#topbar").render())
        assert "wAgent" in topbar
        assert "1 个工具" in topbar


async def test_sidebar_lists_tools():
    app = AgentTUI(make_agent())
    async with app.run_test() as pilot:
        await pilot.pause()
        tools = str(app.query_one("#tools-info").render())
        assert "echo" in tools


async def test_greeting_on_mount():
    app = AgentTUI(make_agent())
    async with app.run_test() as pilot:
        await pilot.pause()
        chat = app.query_one("#chat")
        assert len(chat.children) == 1
        assert isinstance(chat.children[0], AssistantMessage)


# ---------------------------------------------------------------- 对话
async def test_user_message_appears():
    app = AgentTUI(make_agent())
    async with app.run_test() as pilot:
        await pilot.pause()
        await submit(app, pilot, "你好")
        messages = [c for c in app.query_one("#chat").children if isinstance(c, UserMessage)]
        assert len(messages) == 1
        assert messages[0].text == "你好"


async def test_assistant_streams_into_one_bubble():
    app = AgentTUI(make_agent())
    async with app.run_test() as pilot:
        await pilot.pause()
        await submit(app, pilot, "hi")
        assistant = [
            c for c in app.query_one("#chat").children if isinstance(c, AssistantMessage)
        ]
        # 问候语 + 一条回答（两个 TEXT_DELTA 应合并为一条）
        assert len(assistant) == 2
        assert assistant[-1].text == "你好，世界"


async def test_tool_card_created_and_finished():
    app = AgentTUI(make_agent(ToolThenTextClient()))
    async with app.run_test() as pilot:
        await pilot.pause()
        await submit(app, pilot, "调用工具")

        cards = [c for c in app.query_one("#chat").children if isinstance(c, ToolCard)]
        assert len(cards) == 1
        card = cards[0]
        assert card.tool_name == "echo"
        assert not card.has_class("running")          # 已完成
        assert "echo:x" in str(card._result_body.render())
        assert "ms" in card._collapsible.title


# ---------------------------------------------------------------- 状态
async def test_status_counts_round_and_tools():
    app = AgentTUI(make_agent(ToolThenTextClient()))
    async with app.run_test() as pilot:
        await pilot.pause()
        await submit(app, pilot, "调用工具")
        status = str(app.query_one("#statusbar").render())
        assert "1 轮" in status
        assert "工具 1 次" in status


async def test_new_session_resets_counters():
    app = AgentTUI(make_agent())
    async with app.run_test() as pilot:
        await pilot.pause()
        await submit(app, pilot, "hi")
        app.action_new_session()
        await pilot.pause()

        assert len(app.query_one("#chat").children) == 1     # 只剩问候语
        status = str(app.query_one("#statusbar").render())
        assert "0 轮" in status


# ---------------------------------------------------------------- 命令
async def test_slash_clear():
    app = AgentTUI(make_agent())
    async with app.run_test() as pilot:
        await pilot.pause()
        await submit(app, pilot, "/clear")
        assert len(app.query_one("#chat").children) == 0


async def test_slash_tools_lists_names():
    app = AgentTUI(make_agent())
    async with app.run_test() as pilot:
        await pilot.pause()
        await submit(app, pilot, "/tools")
        last = app.query_one("#chat").children[-1]
        assert "echo" in last.text


async def test_unknown_command_reports():
    app = AgentTUI(make_agent())
    async with app.run_test() as pilot:
        await pilot.pause()
        await submit(app, pilot, "/nope")
        assert "未知命令" in app.query_one("#chat").children[-1].text


async def test_help_screen_opens_and_closes():
    from tui.screens.help import HelpScreen

    app = AgentTUI(make_agent())
    async with app.run_test() as pilot:
        await pilot.pause()
        app.action_help()
        await pilot.pause()
        assert isinstance(app.screen, HelpScreen)
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, HelpScreen)


async def test_sidebar_toggle():
    app = AgentTUI(make_agent())
    async with app.run_test() as pilot:
        await pilot.pause()
        sidebar = app.query_one("#sidebar")
        assert not sidebar.has_class("hidden")
        app.action_toggle_sidebar()
        await pilot.pause()
        assert sidebar.has_class("hidden")
