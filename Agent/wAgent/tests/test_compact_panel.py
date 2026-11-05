"""压缩对比面板测试。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from core.context.compactor import CompactResult  # noqa: E402
from tui.screens.compact_compare import CompactCompareScreen  # noqa: E402

BEFORE = "\n".join(f"第 {i} 行：压缩前原始内容" for i in range(40))
AFTER = "# 摘要\n\n- 要点一\n- 要点二"


class HostApp:
    """占位，避免导入 App 造成循环。"""


def make_screen(**kwargs):
    from textual.app import App

    class T(App):
        def on_mount(self) -> None:
            self.push_screen(
                CompactCompareScreen(BEFORE, AFTER, **kwargs)
            )

    return T()


@pytest.mark.asyncio
async def test_panel_opens_with_two_panes():
    app = make_screen(archive_id="20261105-111345", before_tokens=5000, after_tokens=1200)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, CompactCompareScreen)
        assert len(screen.query(".pane-scroll")) == 2


@pytest.mark.asyncio
async def test_panel_shows_counts_and_archive():
    app = make_screen(archive_id="20261105-111345", before_tokens=5000, after_tokens=1200)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        title = str(app.screen.query_one("#compare-title").render())
        assert "20261105-111345" in title
        assert "4.9k" in title          # 5000/1024
        assert "1.2k" in title

        left = str(app.screen.query_one("#left-header").render())
        right = str(app.screen.query_one("#right-header").render())
        assert "压缩前" in left
        assert "压缩后" in right


@pytest.mark.asyncio
async def test_panes_scroll_independently():
    app = make_screen()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        panes = list(app.screen.query(".pane-scroll"))
        left, right = panes[0], panes[1]

        assert left.scroll_y == 0
        left.scroll_down(animate=False)
        await pilot.pause()
        assert left.scroll_y > 0
        assert right.scroll_y == 0        # 互不影响


@pytest.mark.asyncio
async def test_close_button_dismisses():
    app = make_screen()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await pilot.click("#close-btn")
        await pilot.pause()
        assert not isinstance(app.screen, CompactCompareScreen)


@pytest.mark.asyncio
async def test_escape_dismisses():
    app = make_screen()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, CompactCompareScreen)


def test_result_carries_compare_text():
    """CompactResult 应带上对比面板所需的原文与摘要。"""
    result = CompactResult(
        archive_id="20261105-111345",
        archive_path=Path("x.jsonl"),
        before_tokens=5000,
        after_tokens=1200,
        summary_tokens=1100,
        before_text=BEFORE,
        summary=AFTER,
    )
    assert result.before_text == BEFORE
    assert result.summary == AFTER


def test_compactor_fills_compare_fields(tmp_path):
    """真实压缩流程应填充 before_text 与 summary。"""
    from core.agent.engine import Agent
    from core.config import AgentSettings
    from core.context import Compactor
    from core.llm.client import LLMClient, StreamChunk
    from core.tools.base import ToolRegistry

    class Fake(LLMClient):
        def stream(self, messages, tools=None):
            return iter([StreamChunk(text="ok")])

        def complete(self, messages, tools=None):
            return "# 摘要\n\n用户想查宠物。"

    agent = Agent(AgentSettings(), Fake(), ToolRegistry())
    list(agent.stream_reply("查住院中的宠物"))

    _, result = Compactor(agent._client, tmp_path).compact(agent.history)
    assert result.before_text
    assert "查住院中的宠物" in result.before_text
    assert result.summary.startswith("# 摘要")
    assert result.archive_id in str(result.archive_path)
