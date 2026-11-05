"""会话持久化、AGENTS.md、命令面板与 MCP 异步加载的测试。"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from core.agent.engine import Agent  # noqa: E402
from core.config import AgentSettings  # noqa: E402
from core.llm.client import LLMClient, StreamChunk  # noqa: E402
from core.session import (  # noqa: E402
    INJECTION_MARKER,
    SessionError,
    SessionManager,
    build_injection_message,
    find_agents_md,
    is_injected,
    list_sessions,
    load_agents_md,
    load_session,
    save_session,
)
from core.tools.base import ToolRegistry  # noqa: E402


class Echo(LLMClient):
    def stream(self, messages, tools=None):
        return iter([StreamChunk(text="好的")])


def make_agent(system_prompt_extra: str = "") -> Agent:
    return Agent(AgentSettings(), Echo(), ToolRegistry(), system_prompt_extra, "deepseek-chat")


# ================================================================== 会话存储
def test_save_and_load_session(tmp_path):
    agent = make_agent()
    list(agent.stream_reply("第一个问题"))

    path = save_session("20261105-120000", agent.history, tmp_path)
    assert path.is_file()

    messages, meta = load_session("20261105-120000", tmp_path)
    assert meta.session_id == "20261105-120000"
    assert meta.title == "第一个问题"
    assert any(m["role"] == "user" for m in messages)


def test_session_preserves_tool_calls(tmp_path):
    agent = make_agent()
    agent.append_message(
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": "c1", "type": "function",
                 "function": {"name": "getDate", "arguments": "{}"}}
            ],
        }
    )
    agent.append_message({"role": "tool", "tool_call_id": "c1", "content": "2026-11-05"})
    save_session("20261105-120001", agent.history, tmp_path)

    messages, _ = load_session("20261105-120001", tmp_path)
    assistant = next(m for m in messages if m.get("tool_calls"))
    tool_msg = next(m for m in messages if m["role"] == "tool")
    assert assistant["tool_calls"][0]["function"]["name"] == "getDate"
    assert tool_msg["tool_call_id"] == "c1"


def test_save_empty_session_raises(tmp_path):
    with pytest.raises(SessionError):
        save_session("20261105-120002", [], tmp_path)


def test_load_missing_session_raises(tmp_path):
    with pytest.raises(SessionError, match="找不到会话"):
        load_session("20990101-000000", tmp_path)


def test_list_sessions_newest_first(tmp_path):
    for sid in ("20261105-120000", "20261106-120000", "20261104-120000"):
        save_session(sid, [{"role": "user", "content": "x"}], tmp_path)
    metas = list_sessions(tmp_path)
    assert metas[0].session_id == "20261106-120000"


# ================================================================== AGENTS.md
def test_find_agents_md(tmp_path):
    assert find_agents_md(tmp_path) is None
    (tmp_path / "AGENTS.md").write_text("# 约定", encoding="utf-8")
    assert find_agents_md(tmp_path) is not None


def test_load_agents_md_content(tmp_path):
    (tmp_path / "AGENTS.md").write_text("# 项目\n\n- 用中文\n", encoding="utf-8")
    agents = load_agents_md(tmp_path)
    assert agents is not None
    assert "用中文" in agents.content


def test_load_agents_md_empty_returns_none(tmp_path):
    (tmp_path / "AGENTS.md").write_text("   \n\n", encoding="utf-8")
    assert load_agents_md(tmp_path) is None


def test_agents_md_truncated(tmp_path):
    (tmp_path / "AGENTS.md").write_text("x" * 500, encoding="utf-8")
    agents = load_agents_md(tmp_path, max_chars=100)
    assert agents.truncated
    assert len(agents.content) < 500


def test_injection_message_has_marker(tmp_path):
    (tmp_path / "AGENTS.md").write_text("- 规则", encoding="utf-8")
    agents = load_agents_md(tmp_path)
    message = build_injection_message(agents)
    assert message["role"] == "user"
    assert message["content"].startswith(INJECTION_MARKER)


def test_is_injected_detects():
    assert is_injected([{"role": "user", "content": INJECTION_MARKER + "\nx"}])
    assert not is_injected([{"role": "user", "content": "普通消息"}])


def test_manager_injects_once(tmp_path):
    """一次注入，全程复用：第二次调用不再注入。"""
    (tmp_path / "AGENTS.md").write_text("- 规则一", encoding="utf-8")
    agent = make_agent()
    sm = SessionManager(project_root=tmp_path)

    first = sm.prepare_agents_md(agent)
    assert first is not None
    count_after_first = len(agent.history)

    second = sm.prepare_agents_md(agent)
    assert second is None
    assert len(agent.history) == count_after_first


def test_injected_agents_md_persisted(tmp_path):
    """注入的消息应随会话被保存到事件日志。"""
    (tmp_path / "AGENTS.md").write_text("- 持久化规则", encoding="utf-8")
    agent = make_agent()
    sm = SessionManager(project_root=tmp_path)
    sm.prepare_agents_md(agent)

    path = sm.save(agent)
    text = path.read_text(encoding="utf-8")
    assert "持久化规则" in text
    assert INJECTION_MARKER in text


def test_resume_restores_agents_injected_flag(tmp_path):
    (tmp_path / "AGENTS.md").write_text("- 规则", encoding="utf-8")
    agent = make_agent()
    sm = SessionManager(project_root=tmp_path)
    sm.prepare_agents_md(agent)
    sid = sm.state.session_id
    sm.save(agent)

    fresh = make_agent()
    sm2 = SessionManager(project_root=tmp_path)
    sm2.resume(fresh, sid)
    assert sm2.state.agents_injected is True
    # 恢复后不应重复注入
    assert sm2.prepare_agents_md(fresh) is None


# ================================================================== SessionManager
def test_manager_new_session_changes_id(tmp_path):
    sm = SessionManager(project_root=tmp_path)
    old = sm.state.session_id
    new = sm.start_new().session_id
    assert new != old


def test_manager_save_and_list(tmp_path):
    agent = make_agent()
    list(agent.stream_reply("你好"))
    sm = SessionManager(project_root=tmp_path)
    sm.save(agent)
    assert len(sm.list()) == 1


def test_manager_autosave_disabled(tmp_path):
    agent = make_agent()
    list(agent.stream_reply("你好"))
    sm = SessionManager(project_root=tmp_path, autosave=False)
    assert sm.autosave(agent) is None
    assert sm.list() == []


# ================================================================== 命令定义
def test_commands_cover_required():
    from tui.screens.palette import names

    available = names()
    for required in ("/new", "/resume", "/save", "/quit"):
        assert required in available


def test_more_than_four_commands():
    from tui.screens.palette import COMMANDS

    assert len(COMMANDS) >= 10


def test_find_by_prefix():
    from tui.screens.palette import find

    assert any(c.name == "/new" for c in find("/n"))
    assert [c.name for c in find("/compact")][0] == "/compact"


def test_get_command():
    from tui.screens.palette import get

    assert get("/save") is not None
    assert get("/不存在") is None


# ================================================================== 面板交互
@pytest.mark.asyncio
async def test_palette_select_returns_command():
    from textual.app import App

    from tui.screens.palette import CommandPalette

    picked = {}

    class T(App):
        def on_mount(self) -> None:
            self.push_screen(CommandPalette("/"), lambda r: picked.setdefault("v", r))

    app = T()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await pilot.press("down")
        await pilot.press("enter")
        await pilot.pause()
    assert picked["v"] in {c.name for c in __import__(
        "tui.screens.palette", fromlist=["COMMANDS"]).COMMANDS}


@pytest.mark.asyncio
async def test_palette_escape_cancels():
    from textual.app import App

    from tui.screens.palette import CommandPalette

    picked = {}

    class T(App):
        def on_mount(self) -> None:
            self.push_screen(CommandPalette("/"), lambda r: picked.setdefault("v", r))

    app = T()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
    assert picked["v"] is None


@pytest.mark.asyncio
async def test_session_picker_selects():
    from textual.app import App

    from core.session import SessionMeta
    from tui.screens.session_picker import SessionPickerScreen

    metas = [SessionMeta(session_id=f"2026110{i}-120000", title=f"会话{i}", message_count=3)
             for i in range(1, 4)]
    picked = {}

    class T(App):
        def on_mount(self) -> None:
            self.push_screen(SessionPickerScreen(metas), lambda r: picked.setdefault("v", r))

    app = T()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await pilot.press("down")
        await pilot.press("enter")
        await pilot.pause()
    assert picked["v"] is metas[1]


@pytest.mark.asyncio
async def test_session_picker_escape_cancels():
    from textual.app import App

    from core.session import SessionMeta
    from tui.screens.session_picker import SessionPickerScreen

    picked = {}

    class T(App):
        def on_mount(self) -> None:
            self.push_screen(
                SessionPickerScreen([SessionMeta(session_id="x", title="t")]),
                lambda r: picked.setdefault("v", r),
            )

    app = T()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
    assert picked["v"] is None


# ================================================================== MCP 异步
def test_mcp_async_load_does_not_connect(tmp_path):
    import json

    from core.mcp import McpManager

    (tmp_path / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"dead": {"url": "http://127.0.0.1:1/mcp"}}}),
        encoding="utf-8",
    )
    manager = McpManager()
    manager.load_config(tmp_path)
    # 只读配置，尚未连接
    assert manager.statuses == []
    assert manager.routes == []


def test_mcp_manager_exposes_async_load_flag(tmp_path):
    """main.py 会读取 mcp.async_load，属性必须存在且与构造参数一致。"""
    import json

    from core.mcp import build_mcp_manager

    (tmp_path / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"dead": {"url": "http://127.0.0.1:1/mcp"}}}),
        encoding="utf-8",
    )

    lazy = build_mcp_manager(project_root=tmp_path, async_load=True)
    assert lazy.async_load is True
    assert lazy.statuses == []          # 延迟模式不连接
    lazy.close()

    eager = build_mcp_manager(project_root=tmp_path, connect_timeout=2.0, async_load=False)
    assert eager.async_load is False
    assert len(eager.statuses) == 1     # 立即模式已尝试连接
    eager.close()


def test_mcp_manager_default_is_eager(tmp_path):
    from core.mcp import McpManager

    assert McpManager().async_load is False


def test_mcp_sync_mode_connects(tmp_path):
    import json

    from core.mcp import build_mcp_manager

    (tmp_path / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"dead": {"url": "http://127.0.0.1:1/mcp"}}}),
        encoding="utf-8",
    )
    manager = build_mcp_manager(project_root=tmp_path, connect_timeout=2.0)
    assert len(manager.statuses) == 1
    assert manager.statuses[0].connected is False
    manager.close()


def test_mcp_tool_sink_called(tmp_path):
    import json

    from core.mcp import McpManager

    (tmp_path / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"dead": {"url": "http://127.0.0.1:1/mcp"}}}),
        encoding="utf-8",
    )
    manager = McpManager(connect_timeout=2.0)
    calls = []
    manager.set_tool_sink(lambda: calls.append(1))
    manager.load_config(tmp_path)
    manager.connect_all()
    assert calls            # 每个服务器结束后都应回调
    manager.close()


def test_agent_register_tools_runtime():
    from core.tools.base import Tool

    class NewTool(Tool):
        name = "runtimeTool"
        description = "运行时注册"

        def run(self) -> str:
            return "ok"

    agent = make_agent()
    before = len(agent.tool_names)
    added = agent.register_tools([NewTool()])
    assert added == ["runtimeTool"]
    assert len(agent.tool_names) == before + 1

    # 重名不重复注册
    assert agent.register_tools([NewTool()]) == []


# ================================================================== 配置集中
def test_no_hardcoded_warn_ratio_in_usage():
    """阈值应由配置注入，模块只是兜底。"""
    from core.context import ContextUsage

    usage = ContextUsage(used=70, window=100, window_is_default=False,
                         measured_by_api=True, warn_ratio=0.5)
    assert usage.needs_compact is True      # 70% > 50%


def test_context_settings_flow_into_usage(tmp_path):
    from core.config import ContextSettings

    agent = make_agent()
    agent._context_settings = ContextSettings(warn_ratio=0.5, default_window=8000)
    usage = agent.context_usage()
    assert usage.warn_ratio == 0.5


def test_recall_tool_uses_config_settings(tmp_path):
    from core.config import ContextSettings
    from core.context import RecallContextTool, save_archive

    save_archive("20261105-130000", [{"role": "user", "content": "关键词内容"}], tmp_path)
    tool = RecallContextTool(tmp_path, ContextSettings(recall_max_snippets=1))
    out = tool.run("关键词")
    assert "关键词" in out
