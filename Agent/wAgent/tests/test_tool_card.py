"""工具卡片与含方括号内容的渲染测试。

回归背景：`Collapsible.title` 会被 `Content.from_text()` 当作 rich markup
解析。工具参数里常见 Windows 路径与 JSON 数组（如
`args=["D:\\office\\x.py"]`），其中的方括号会让渲染抛
`Expected markup value`，导致整条工具卡片变成红色错误信息。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from tui.widgets.tool_card import ToolCard  # noqa: E402

#: 覆盖真实场景中会触发 markup 解析的几类参数
TRICKY_ARGS = [
    {"command": "python", "args": ["D:\\office\\nanchong-ppt\\build_slides.py"]},
    {"args": ["D:\\office\\[abc]\\x.py"]},
    {"command": "powershell", "args": ["-NoProfile", "-Command", "$p='D:\\office\\a.pptx'"]},
    {"args": ["[ERROR]", "[/]", "[b]粗体[/b]"]},
    {"args": ["[link=https://x]a[/link]"]},
]


def _title_text(card: ToolCard) -> str:
    title = card._collapsible.title
    return title.plain if hasattr(title, "plain") else str(title)


@pytest.mark.asyncio
@pytest.mark.parametrize("args", TRICKY_ARGS)
async def test_card_renders_with_bracket_arguments(args):
    """带方括号的参数不应导致渲染异常。"""
    from textual.app import App

    class T(App):
        def compose(self):
            yield ToolCard("RunCli", args)

    app = T()
    async with app.run_test(size=(140, 20)) as pilot:
        await pilot.pause()
        card = app.query_one(ToolCard)
        assert _title_text(card)          # 能取到标题即说明未崩溃


@pytest.mark.asyncio
async def test_card_finish_with_brackets_in_result():
    """工具返回结果里的方括号同样不应破坏渲染。"""
    from textual.app import App

    class T(App):
        def compose(self):
            yield ToolCard("RunCli", {"args": ["D:\\office\\[abc]\\x.py"]})

    app = T()
    async with app.run_test(size=(140, 20)) as pilot:
        await pilot.pause()
        card = app.query_one(ToolCard)
        card.finish("[ERROR] 路径 D:\\office\\[test]\\a.py 不存在", 304.0)
        await pilot.pause()

        rendered = str(card._result_body.render())
        # 原文应完整保留，不出现多余反斜杠
        assert "[ERROR]" in rendered
        assert "D:\\office\\[test]\\a.py" in rendered
        assert "\\\\\\" not in rendered


@pytest.mark.asyncio
async def test_title_keeps_path_verbatim():
    """标题里的路径应原样显示，不多不少。"""
    from textual.app import App

    class T(App):
        def compose(self):
            yield ToolCard("RunCli", {"args": ["D:\\office\\[a]\\b.py"]})

    app = T()
    async with app.run_test(size=(140, 20)) as pilot:
        await pilot.pause()
        text = _title_text(app.query_one(ToolCard))
        assert "D:\\office\\[a]\\b.py" in text
        assert "\\\\\\" not in text        # 没有三重反斜杠


@pytest.mark.asyncio
async def test_card_title_updates_after_finish():
    from textual.app import App

    class T(App):
        def compose(self):
            yield ToolCard("getDate", {})

    app = T()
    async with app.run_test(size=(140, 20)) as pilot:
        await pilot.pause()
        card = app.query_one(ToolCard)
        assert "运行中" in _title_text(card)

        card.finish("2026-11-05", 12.5)
        await pilot.pause()
        assert "运行中" not in _title_text(card)
        assert "12 ms" in _title_text(card)


@pytest.mark.asyncio
async def test_empty_arguments_render():
    from textual.app import App

    class T(App):
        def compose(self):
            yield ToolCard("noop", None)

    app = T()
    async with app.run_test(size=(140, 20)) as pilot:
        await pilot.pause()
        assert "()" in _title_text(app.query_one(ToolCard))


# ---------------------------------------------------------------- 其它组件
@pytest.mark.asyncio
async def test_compact_compare_handles_brackets():
    """原始转录含 [0] user 这类索引，左栏必须能正常渲染。"""
    from textual.app import App

    from tui.screens.compact_compare import CompactCompareScreen

    before = "### [0] user\n改 D:\\office\\[test]\\a.py\n### [1] tool\n[ERROR] 失败"

    class T(App):
        def on_mount(self):
            self.push_screen(CompactCompareScreen(before, "# 摘要\n\n- [x] 完成"))

    app = T()
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        pane = app.screen.query_one(".pane-text")
        assert "[0]" in str(pane.render())


@pytest.mark.asyncio
async def test_session_picker_handles_brackets():
    from textual.app import App

    from core.session import SessionMeta
    from tui.screens.session_picker import SessionPickerScreen

    class T(App):
        def on_mount(self):
            self.push_screen(
                SessionPickerScreen(
                    [SessionMeta(session_id="x", title="修改 [test] 目录", message_count=3)]
                )
            )

    app = T()
    async with app.run_test(size=(120, 20)) as pilot:
        await pilot.pause()
        text = str(app.screen.query_one("#session-0").render())
        assert "[test]" in text


@pytest.mark.asyncio
async def test_notice_handles_brackets():
    from textual.app import App

    from tui.screens.notice import NoticeScreen

    class T(App):
        def on_mount(self):
            self.push_screen(NoticeScreen("需要 [配置] API Key", "### 内容\n`[llm]`"))

    app = T()
    async with app.run_test(size=(100, 24)) as pilot:
        await pilot.pause()
        assert "[配置]" in str(app.screen.query_one("#notice-title").render())


@pytest.mark.asyncio
async def test_message_body_preserves_backslashes():
    """消息正文按纯文本渲染，反斜杠不应被额外转义。"""
    from textual.app import App

    from tui.widgets.message import AssistantMessage

    class T(App):
        def compose(self):
            yield AssistantMessage("路径 D:\\office\\[a]\\b.py")

    app = T()
    async with app.run_test(size=(100, 20)) as pilot:
        await pilot.pause()
        rendered = str(app.query_one(AssistantMessage)._body.render())
        assert "D:\\office\\[a]\\b.py" in rendered
        assert "\\\\\\" not in rendered
