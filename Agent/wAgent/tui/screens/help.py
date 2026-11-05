"""帮助弹窗（/help）。"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

HELP_TEXT = """[#58a6ff][b]使用方式[/b][/]

[#c9d1d9]• 在底部输入框输入问题，[b]Enter[/b] 发送。
• 模型需要调用工具时会自动执行，工具卡片可点击展开查看参数与结果。
• [b]Esc[/b] 中断当前生成；已完成的回答才会写入历史。
• [b]F2 / Ctrl+P[/b] 打开命令补全面板。[/]

[#58a6ff][b]命令[/b][/]

| 命令 | 作用 |
|------|------|
| /help | 打开本帮助 |
| /new | 新建会话（自动保存当前会话） |
| /resume | 恢复历史会话（↑↓ 选择、Enter 确认、Esc 取消） |
| /save | 保存当前会话 |
| /sessions | 列出历史会话 |
| /compact | 压缩上下文（归档原始记录并生成摘要） |
| /compact-preview | 重新查看上次压缩的前后对比 |
| /reset | 重置上下文（不保存） |
| /clear | 清空界面（保留历史） |
| /tools | 列出已注册工具 |
| /skills | 列出已发现技能 |
| /mcp | 显示 MCP 服务器状态 |
| /context | 显示上下文用量详情 |
| /cwd | 显示工作目录 |
| /model | 显示模型与接口 |
| /quit | 退出（会先自动保存会话） |

[#58a6ff][b]上下文管理[/b][/]

[#c9d1d9]• 顶部显示 当前上下文 / 模型窗口 / 占用百分比。
• 达到 70% 时会提示并暂停接受新输入，必须先执行 [b]/compact[/b]。
• 压缩会先把原始记录归档到 .agents/context/，再生成约 5000 tokens 的摘要。
• 压缩期间禁止执行工具，完成后自动解除限制。
• 需要历史细节时，模型可调用 [b]recallContext[/b] 检索归档。[/]

[#58a6ff][b]会话与项目指令[/b][/]

[#c9d1d9]• 会话保存在 .agents/sessions/，退出与 /new 时自动保存。
• 项目根存在 [b]AGENTS.md[/b] 时，会作为一条消息注入聊天历史，
  并随会话一起持久化；后续轮次直接复用，不再重复注入。
• MCP 服务器在后台异步加载，连接完成后侧栏会自动刷新。[/]

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
