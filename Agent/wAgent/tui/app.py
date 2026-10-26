"""Textual TUI：Agent 对话界面。

本层只做三件事：
1. 收集用户输入
2. 把输入交给 core.Agent，消费它产出的 AgentEvent
3. 把事件渲染到界面

不包含任何 LLM / 工具 / 配置逻辑。
"""

from __future__ import annotations

import uuid
from pathlib import Path

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Footer, Input, Static

from core.events import AgentEvent, EventType

from .commands import QUIT_ALIASES, parse
from .widgets.message import AssistantMessage, ErrorMessage, UserMessage
from .widgets.sidebar import Sidebar
from .widgets.status_bar import StatusBar
from .widgets.tool_card import ToolCard


class AgentTUI(App):
    """对话主界面。"""

    CSS_PATH = "theme.tcss"

    BINDINGS = [
        Binding("ctrl+q", "quit", "退出"),
        Binding("ctrl+l", "clear", "清屏"),
        Binding("ctrl+n", "new_session", "新会话"),
        Binding("ctrl+b", "toggle_sidebar", "侧栏"),
        Binding("f1", "help", "帮助"),
        Binding("escape", "interrupt", "中断", show=False),
    ]

    def __init__(self, agent, config_path: Path | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        self._agent = agent
        self._config_path = config_path
        self._busy = False
        self._session_id = uuid.uuid4().hex[:8]
        self._rounds = 0
        self._messages = 0

        # 当前正在流式写入的助手气泡 / 工具卡片
        self._current_assistant: AssistantMessage | None = None
        self._current_tool: ToolCard | None = None

    # ------------------------------------------------------------------ 布局
    def compose(self) -> ComposeResult:
        yield Static(id="topbar")
        with Horizontal(id="main"):
            yield VerticalScroll(id="chat")
            yield Sidebar()
        with Horizontal(id="input-area"):
            yield Input(
                placeholder="输入问题后回车发送；/help 查看命令；Esc 中断生成", id="input"
            )
        yield StatusBar()
        yield Footer()

    def on_mount(self) -> None:
        self.title = "wAgent"
        self._refresh_topbar()
        self._refresh_sidebar()
        self._refresh_status()
        self._greet()
        self.query_one("#input", Input).focus()

    # ------------------------------------------------------------------ 顶栏
    def _refresh_topbar(self) -> None:
        names = getattr(self._agent, "tool_names", [])
        model = self._model_name()
        brand = "[#f0f6fc][b]wAgent[/b][/]"
        bar = self.query_one("#topbar", Static)
        bar.update(
            f"{brand}  ·  {len(names)} 个工具  ·  {model}\n"
            f"[#6e7681]工作目录[/]  {self._workdir()}\n"
            f"[#6e7681]Enter 发送    /help 命令    Esc 中断生成    Ctrl+B 侧栏    Ctrl+N 新会话[/]"
        )

    def _workdir(self) -> str:
        try:
            return str(Path.cwd())
        except OSError:
            return "?"

    def _model_name(self) -> str:
        getter = getattr(self._agent, "model_name", None)
        if callable(getter):
            name = getter()
            if name:
                return name
        return "deepseek-chat"

    # ------------------------------------------------------------------ 侧栏
    def _refresh_sidebar(self) -> None:
        sidebar = self.query_one(Sidebar)
        sidebar.update_session(
            模型=self._model_name(),
            会话=self._session_id,
            轮次=self._rounds,
            消息=self._messages,
            上限=f"{self._max_rounds()} 次模型调用/轮",
            状态="就绪" if not self._busy else "生成中",
        )
        sidebar.update_tools(getattr(self._agent, "tool_specs", []))

    def _max_rounds(self) -> int:
        return getattr(getattr(self._agent, "_settings", None), "max_tool_rounds", 5)

    # ------------------------------------------------------------------ 状态栏
    def _refresh_status(self) -> None:
        bar = self.query_one(StatusBar)
        bar.configure(self._model_name())
        bar._rounds = self._rounds
        bar.refresh_text()

    # ------------------------------------------------------------------ 提示
    def _greet(self) -> None:
        chat = self.query_one("#chat", VerticalScroll)
        chat.mount(
            AssistantMessage(
                "你好！可以问我「今天是几号？」，或让我搜索网页、执行本地命令。\n"
                "输入 /help 查看全部命令。"
            )
        )

    # ------------------------------------------------------------------ 输入
    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if not text:
            return
        event.input.value = ""

        cmd, rest = parse(text)
        if cmd:
            self._dispatch_command(cmd, rest)
            return

        if self._busy:
            self._toast("正在生成中，请稍候或按 Esc 中断", "busy")
            return

        self._start_round(text)

    # ------------------------------------------------------------------ 命令
    def _dispatch_command(self, cmd: str, rest: str) -> None:
        if cmd in QUIT_ALIASES:
            self.exit()
        elif cmd == "/help":
            self.action_help()
        elif cmd == "/clear":
            self.action_clear()
        elif cmd == "/new":
            self.action_new_session()
        elif cmd == "/tools":
            self._show_tools()
        elif cmd == "/cwd":
            self._chat_notice(f"工作目录：{self._workdir()}")
        elif cmd == "/model":
            self._chat_notice(f"模型：{self._model_name()}\n配置文件：{self._config_path or 'config.ini'}")
        else:
            self._chat_notice(f"未知命令 {cmd}，输入 /help 查看可用命令。")

    def _show_tools(self) -> None:
        specs = getattr(self._agent, "tool_specs", [])
        if not specs:
            self._chat_notice("尚未注册任何工具。")
            return
        lines = [f"已注册 {len(specs)} 个工具："]
        for i, item in enumerate(specs, 1):
            lines.append(f"{i}. {item['name']} — {item['description']}")
        self._chat_notice("\n".join(lines))

    def _chat_notice(self, text: str) -> None:
        """把命令结果以助手气泡形式显示在会话区。"""
        self.query_one("#chat", VerticalScroll).mount(AssistantMessage(text))
        self._scroll_end()

    def _toast(self, text: str, style: str = "ok") -> None:
        self.query_one(StatusBar).set_state(text, style)

    # ------------------------------------------------------------------ 对话
    def _start_round(self, prompt: str) -> None:
        chat = self.query_one("#chat", VerticalScroll)
        chat.mount(UserMessage(prompt))
        self._messages += 1
        self._current_assistant = None
        self._current_tool = None
        self._busy = True
        self._toast("生成中…", "busy")
        self.query_one("#input", Input).disabled = False
        self._run_agent(prompt)
        self._scroll_end()

    @work(thread=True, exclusive=True)
    def _run_agent(self, prompt: str) -> None:
        """在后台线程跑同步生成器，事件回主线程渲染。"""
        try:
            for event in self._agent.stream_reply(prompt):
                self.call_from_thread(self._handle_event, event)
        except Exception as exc:  # noqa: BLE001 展示给用户
            self.call_from_thread(self._handle_error, str(exc))
        finally:
            self.call_from_thread(self._finish_round)

    # ------------------------------------------------------------------ 渲染
    def _handle_event(self, event: AgentEvent) -> None:
        if event.type is EventType.ROUND_STARTED:
            return

        if event.type is EventType.TEXT_DELTA:
            self._append_assistant(event.text)
        elif event.type is EventType.TOOL_CALL_STARTED:
            self._add_tool_card(event)
        elif event.type is EventType.TOOL_CALL_FINISHED:
            self._finish_tool_card(event)
        elif event.type is EventType.ROUND_FINISHED:
            self._current_assistant = None
            self._current_tool = None
            self._rounds += 1
            self._messages += 1
            self.query_one(StatusBar).add_round(
                int(event.payload.get("tool_calls", 0)), event.payload.get("duration_ms")
            )
        elif event.type is EventType.ERROR:
            self.query_one("#chat", VerticalScroll).mount(
                ErrorMessage(str(event.payload.get("message", "")))
            )

        self._scroll_end()

    def _append_assistant(self, piece: str) -> None:
        if self._current_assistant is None:
            self._current_assistant = AssistantMessage("")
            self.query_one("#chat", VerticalScroll).mount(self._current_assistant)
            self._messages += 1
        self._current_assistant.append_text(piece)

    def _add_tool_card(self, event: AgentEvent) -> None:
        # 工具调用意味着上一段助手文本结束
        self._current_assistant = None
        card = ToolCard(event.tool_name, event.payload.get("arguments") or {})
        self._current_tool = card
        self.query_one("#chat", VerticalScroll).mount(card)

    def _finish_tool_card(self, event: AgentEvent) -> None:
        if self._current_tool is not None:
            self._current_tool.finish(
                str(event.payload.get("result", "")), event.payload.get("duration_ms")
            )
            self._current_tool = None

    def _handle_error(self, message: str) -> None:
        self.query_one("#chat", VerticalScroll).mount(ErrorMessage(message))
        self._scroll_end()

    def _finish_round(self) -> None:
        self._busy = False
        self._current_assistant = None
        self._current_tool = None
        self._toast("就绪")
        self._refresh_sidebar()
        self._scroll_end()

    def _scroll_end(self) -> None:
        try:
            self.query_one("#chat", VerticalScroll).scroll_end(animate=False)
        except Exception:  # noqa: BLE001 界面拆卸时忽略
            pass

    # ------------------------------------------------------------------ 动作
    def action_clear(self) -> None:
        self.query_one("#chat", VerticalScroll).remove_children()
        self._current_assistant = None
        self._toast("界面已清空（历史保留）")

    def action_new_session(self) -> None:
        reset = getattr(self._agent, "reset", None)
        if callable(reset):
            reset()
        self.query_one("#chat", VerticalScroll).remove_children()
        self._current_assistant = None
        self._current_tool = None
        self._session_id = uuid.uuid4().hex[:8]
        self._rounds = 0
        self._messages = 0
        self.query_one(StatusBar).reset_counters()
        self._greet()
        self._refresh_sidebar()
        self._toast("已新建会话")

    def action_toggle_sidebar(self) -> None:
        self.query_one(Sidebar).toggle_class("hidden")

    def action_help(self) -> None:
        from .screens.help import HelpScreen

        self.push_screen(HelpScreen())

    def action_interrupt(self) -> None:
        if self._busy:
            self.workers.cancel_all()
            self._busy = False
            self._current_assistant = None
            self._current_tool = None
            self._toast("已中断")
