"""帮助弹窗（/help）。"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

HELP_TEXT = """[#58a6ff][b]使用方式[/b][/]

[#c9d1d9]• 在底部输入框输入问题，[b]Enter[/b] 发送。
• 模型需要调用工具时会自动执行，工具卡片可点击展开查看参数与结果。
• [b]Esc[/b] 中断当前生成；已完成的回答才会写入历史。[/]

[#58a6ff][b]命令[/b][/]

| 命令 | 作用 |
|------|------|
| /help | 打开本帮助 |
| /clear | 清空界面（保留历史） |
| /new | 新建会话（重置历史） |
| /tools | 列出已注册工具 |
| /cwd | 显示工作目录 |
| /model | 显示模型与接口 |
| /quit | 退出 |

[#58a6ff][b]快捷键[/b][/]

[#c9d1d9]Enter 发送 · Esc 中断 · Ctrl+L 清屏 · Ctrl+N 新会话
Ctrl+B 侧栏 · Ctrl+Q 退出[/]"""


class HelpScreen(ModalScreen):
    """按 Esc 或任意键关闭的帮助层。"""

    BINDINGS = [
        ("escape", "dismiss", "关闭"),
        ("f1", "dismiss", "关闭"),
        ("q", "dismiss", "关闭"),
    ]

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="help-box"):
            yield Static(HELP_TEXT, markup=True)

    def action_dismiss(self) -> None:
        self.app.pop_screen()
