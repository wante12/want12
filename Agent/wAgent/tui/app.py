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
from .widgets.context_meter import ContextMeter
from .widgets.message import AssistantMessage, ErrorMessage, UserMessage
from .widgets.sidebar import Sidebar
from .widgets.status_bar import StatusBar
from .widgets.tool_card import ToolCard


def metadata_id(meta) -> str:
    """取会话编号，兼容对象与字典两种形态。"""
    if meta is None:
        return ""
    return getattr(meta, "session_id", "") or ""


class AgentTUI(App):
    """对话主界面。"""

    CSS_PATH = "theme.tcss"

    #: 会弹出面板的命令：其回调异步执行，需延长补全面板的抑制时间
    _DELAYED_COMMANDS = frozenset({"/resume", "/compact", "/compact-preview", "/help"})

    BINDINGS = [
        Binding("ctrl+q", "quit", "退出"),
        Binding("ctrl+l", "clear", "清屏"),
        Binding("ctrl+n", "new_session", "新会话"),
        Binding("ctrl+p", "palette", "命令补全"),
        Binding("f2", "palette", "命令补全", show=False),
        Binding("ctrl+b", "toggle_sidebar", "侧栏"),
        Binding("f1", "help", "帮助"),
        Binding("escape", "interrupt", "中断", show=False),
    ]

    def __init__(
        self,
        agent,
        config_path: Path | None = None,
        skills=None,
        mcp=None,
        project_root: Path | None = None,
        sessions=None,
        boot_notice: tuple[str, str] | None = None,
        mcp_async: bool = True,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._agent = agent
        self._config_path = config_path
        self._skills = skills
        self._mcp = mcp
        self._project_root = Path(project_root) if project_root else Path.cwd()
        self._sessions = sessions
        self._boot_notice = boot_notice
        self._mcp_async = mcp_async
        self._mcp_loading = False
        self._busy = False
        self._session_id = (
            sessions.state.session_id if sessions is not None else uuid.uuid4().hex[:8]
        )
        self._rounds = 0
        self._messages = 0
        self._compacting = False
        self._last_compact_result = None
        self._palette_open = False
        self._suppress_palette = False

        # 当前正在流式写入的助手气泡 / 工具卡片
        self._current_assistant: AssistantMessage | None = None
        self._current_tool: ToolCard | None = None

    # ------------------------------------------------------------------ 布局
    def compose(self) -> ComposeResult:
        yield Static(id="topbar")
        yield ContextMeter()
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
        self._refresh_context()
        self._refresh_sidebar()
        self._refresh_status()
        self._greet()
        self.query_one("#input", Input).focus()

        # 启动提示（config.ini 新建等）
        if self._boot_notice is not None:
            title, body = self._boot_notice

            def _show() -> None:
                from .screens.notice import NoticeScreen

                try:
                    self.push_screen(NoticeScreen(title, body, quit_on_close=True))
                except Exception:  # noqa: BLE001
                    pass

            self.set_timer(0.3, _show)
            return

        # 异步加载 MCP：先进入界面，连接完成后再刷新
        if self._mcp is not None and self._mcp_async:
            self._start_mcp_async()
        else:
            self._refresh_sidebar()

    # ------------------------------------------------------------------ MCP 异步
    def _start_mcp_async(self) -> None:
        """后台连接 MCP，期间界面可正常使用。"""
        self._mcp_loading = True
        self._refresh_sidebar()
        self._mcp_worker()

    @work(thread=True, exclusive=True)
    def _mcp_worker(self) -> None:
        """在线程里连接所有 MCP Server，逐个回调刷新界面。"""
        mcp = self._mcp
        if mcp is None:
            return

        def _tick() -> None:
            # 从工作线程回到 UI 线程刷新侧栏
            try:
                self.call_from_thread(self._on_mcp_progress)
            except Exception:  # noqa: BLE001
                pass

        try:
            set_sink = getattr(mcp, "set_tool_sink", None)
            if callable(set_sink):
                set_sink(_tick)

            load_config = getattr(mcp, "load_config", None)
            connect_all = getattr(mcp, "connect_all", None)

            if callable(load_config) and callable(connect_all):
                load_config(self._project_root, self._mcp_filename())
                connect_all()
            else:  # 旧接口兜底
                mcp.start(self._project_root, self._mcp_filename())
        except Exception:  # noqa: BLE001 异步加载绝不影响主界面
            pass
        finally:
            try:
                self.call_from_thread(self._on_mcp_done)
            except Exception:  # noqa: BLE001
                pass

    def _mcp_filename(self) -> str:
        config = getattr(self, "_app_config", None)
        return getattr(getattr(config, "mcp", None), "filename", ".mcp.json")

    def _on_mcp_progress(self) -> None:
        """某个服务器连上后增量刷新。"""
        self._register_new_mcp_tools()
        self._refresh_sidebar()
        self._refresh_topbar()

    def _on_mcp_done(self) -> None:
        self._mcp_loading = False
        self._register_new_mcp_tools()
        self._refresh_sidebar()
        self._refresh_topbar()
        statuses = getattr(self._mcp, "statuses", []) if self._mcp else []
        connected = sum(1 for s in statuses if s.connected)
        if statuses:
            self._toast(f"MCP {connected}/{len(statuses)} 已连接", "ok")

    def _register_new_mcp_tools(self) -> None:
        """把新发现的 MCP 工具注册进 Agent 的工具集。"""
        mcp = self._mcp
        if mcp is None:
            return
        register = getattr(self._agent, "register_tools", None)
        if not callable(register):
            return
        try:
            from core.mcp import build_mcp_tools

            existing = set(getattr(self._agent, "tool_names", []))
            new_tools = [
                t for t in build_mcp_tools(mcp) if t.name not in existing
            ]
            if new_tools:
                register(new_tools)
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------ 顶栏
    def _refresh_topbar(self) -> None:
        names = getattr(self._agent, "tool_names", [])
        model = self._model_name()
        skill_count = len(self._skills) if self._skills else 0
        brand = "[#f0f6fc][b]wAgent[/b][/]"
        bar = self.query_one("#topbar", Static)
        bar.update(
            f"{brand}  ·  {len(names)} 个工具  ·  {skill_count} 个技能  ·  {model}\n"
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
        sidebar.update_skills(self._skill_specs())
        sidebar.update_mcp(self._mcp_status())

    def _skill_specs(self) -> list[dict[str, str]]:
        if not self._skills:
            return []
        specs = getattr(self._skills, "specs", None)
        return specs() if callable(specs) else []

    def _mcp_status(self) -> list[dict[str, object]]:
        """MCP 服务器状态，供侧栏渲染。"""
        if not self._mcp:
            return []
        rows: list[dict[str, object]] = []
        for status in getattr(self._mcp, "statuses", []):
            rows.append(
                {
                    "name": status.name,
                    "connected": status.connected,
                    "tool_count": status.tool_count,
                    "error": status.error,
                }
            )
        return rows

    def _max_rounds(self) -> int:
        """每轮允许调用模型的总次数。

        引擎按「工具轮数 + 1」循环，因此实际调用次数恒等于
        max_tool_rounds + 1。这里以它为准，而不是读
        max_model_calls_per_round——后者只是给人看的声明值，
        一旦被覆盖（如 build_agent(max_tool_rounds=N)）就会与实际不符。
        """
        settings = getattr(self._agent, "_settings", None)
        tool_rounds = getattr(settings, "max_tool_rounds", None)
        if isinstance(tool_rounds, int) and tool_rounds >= 0:
            return tool_rounds + 1
        declared = getattr(settings, "max_model_calls_per_round", None)
        return declared if isinstance(declared, int) and declared > 0 else 1

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
    def action_palette(self) -> None:
        """F2 / Ctrl+P：打开命令补全面板。

        采用主动唤起而不是「输入 / 自动弹出」，是为了避免
        面板关闭后残留的 Input.Changed 事件再次触发补全。
        """
        if type(self.screen).__name__ != "Screen":
            return
        try:
            prefix = self.query_one("#input", Input).value or "/"
        except Exception:  # noqa: BLE001
            prefix = "/"
        self._open_palette(prefix if prefix.startswith("/") else "/")

    def _open_palette(self, prefix: str) -> None:
        from .screens.palette import CommandPalette

        self._palette_open = True
        screen = CommandPalette(prefix)

        def _after(selected) -> None:
            self._palette_open = False
            if not selected:
                return
            try:
                field = self.query_one("#input", Input)
                field.value = selected + " "
                field.cursor_position = len(field.value)
                field.focus()
            except Exception:  # noqa: BLE001
                pass

        def _push() -> None:
            try:
                self.push_screen(screen, _after)
            except Exception:  # noqa: BLE001
                self._palette_open = False

        self.set_timer(0.05, _push)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        if not text:
            return
        event.input.value = ""

        cmd, rest = parse(text)

        # 压缩期间：只放行 /compact，其余一律拒绝
        if self._compacting and cmd != "/compact":
            self._toast("正在压缩上下文，暂时禁止输入", "busy")
            self._chat_notice("正在压缩上下文，暂时禁止输入。请等待压缩完成。")
            return

        if cmd:
            # 命令执行期间抑制补全面板（清空输入会触发 Input.Changed）
            # 面板类命令的回调是异步调度的，所以抑制要延续一小段时间
            self._suppress_palette = True
            self._palette_open = False
            try:
                self._dispatch_command(cmd, rest)
            finally:
                if cmd in self._DELAYED_COMMANDS:
                    self.set_timer(0.6, self._release_palette)
                else:
                    self._suppress_palette = False
            return

        if self._busy:
            self._toast("正在生成中，请稍候或按 Esc 中断", "busy")
            return

        # 达到阈值后暂停接受新提示词，直到压缩完成
        usage = self._agent.context_usage() if hasattr(self._agent, "context_usage") else None
        if usage is not None and usage.needs_compact:
            self._toast("上下文已达 70%，请先执行 /compact", "err")
            self._chat_notice(
                f"⚠ 上下文已占用 {usage.percent:.0f}%"
                f"（{usage.used / 1024:.1f}k / {usage.window / 1024:.0f}k），"
                "已达到 70% 阈值。\n请先执行 /compact 压缩上下文，压缩成功后才能继续输入。"
            )
            return

        self._start_round(text)

    # ------------------------------------------------------------------ 命令
    def _dispatch_command(self, cmd: str, rest: str) -> None:
        if cmd in QUIT_ALIASES:
            self.action_quit_saving()
        elif cmd == "/help":
            self.action_help()
        elif cmd == "/clear":
            self.action_clear()
        elif cmd == "/new":
            self.action_new_session()
        elif cmd == "/reset":
            self.action_reset()
        elif cmd == "/resume":
            self.action_resume()
        elif cmd == "/save":
            self.action_save(rest)
        elif cmd == "/sessions":
            self._show_sessions()
        elif cmd == "/compact":
            self.action_compact()
        elif cmd == "/compact-preview":
            self._show_last_compact()
        elif cmd == "/tools":
            self._show_tools()
        elif cmd == "/skills":
            self._show_skills()
        elif cmd == "/mcp":
            self._show_mcp()
        elif cmd == "/cwd":
            self._chat_notice(f"工作目录：{self._workdir()}")
        elif cmd == "/model":
            self._chat_notice(f"模型：{self._model_name()}\n配置文件：{self._config_path or 'config.ini'}")
        elif cmd == "/context":
            self._show_context()
        else:
            self._chat_notice(f"未知命令 {cmd}，输入 /help 查看可用命令。")

    # ------------------------------------------------------------------ 会话命令
    def action_save(self, name: str = "") -> None:
        """保存当前会话。"""
        sm = self._sessions
        if sm is None:
            self._chat_notice("会话管理未启用，无法保存。")
            return
        try:
            path = sm.save(self._agent)
        except Exception as exc:  # noqa: BLE001
            self._toast("保存失败", "err")
            self._chat_notice(f"保存失败：{exc}")
            return
        label = f"「{name.strip()}」" if name.strip() else ""
        self._toast("会话已保存", "ok")
        self._chat_notice(f"✓ 会话{label}已保存\n{path}")

    def action_quit_saving(self) -> None:
        """退出前自动保存（若配置开启）。"""
        sm = self._sessions
        if sm is not None:
            try:
                sm.autosave(self._agent)
            except Exception:  # noqa: BLE001
                pass
        self.exit()

    def action_reset(self) -> None:
        """重置上下文（不保存）。"""
        reset = getattr(self._agent, "reset", None)
        if callable(reset):
            reset()
        self.query_one("#chat", VerticalScroll).remove_children()
        self._last_compact_result = None
        self._toast("已重置上下文")
        self._chat_notice("上下文已重置（未保存）。输入 /save 可先保存会话。")
        self._refresh_context()

    def action_new_session(self) -> None:
        """新建会话，并自动保存当前会话。"""
        sm = self._sessions
        saved = None
        if sm is not None:
            try:
                saved = sm.autosave(self._agent)
            except Exception:  # noqa: BLE001
                saved = None
            sm.start_new()

        reset = getattr(self._agent, "reset", None)
        if callable(reset):
            reset()
        self.query_one("#chat", VerticalScroll).remove_children()
        self._last_compact_result = None
        self._session_id = sm.state.session_id if sm else uuid.uuid4().hex[:8]

        # 新会话同样注入 AGENTS.md（一次注入）
        injected = None
        if sm is not None:
            try:
                injected = sm.prepare_agents_md(self._agent)
            except Exception:  # noqa: BLE001
                injected = None

        self._toast("新会话已开始")
        parts = ["✓ 已开始新会话"]
        if saved:
            parts.append(f"当前会话已自动保存到 {saved.name}")
        if injected:
            parts.append(injected)
        self._chat_notice("\n".join(parts))
        self._refresh_context()
        self._refresh_sidebar()

    def action_resume(self) -> None:
        """弹出历史会话列表。"""
        from .screens.session_picker import SessionPickerScreen

        sm = self._sessions
        if sm is None:
            self._chat_notice("会话管理未启用。")
            return

        metas = sm.list()
        if not metas:
            self._chat_notice("还没有历史会话。用 /save 保存当前会话后再试。")
            return

        screen = SessionPickerScreen(metas)
        # 稍后弹出：避免当前这次 Enter 键被新面板立刻消费掉
        self.set_timer(0.05, lambda: self.push_screen(screen, self._on_session_picked))

    def _on_session_picked(self, meta) -> None:
        if meta is None:
            return
        sm = self._sessions
        if sm is None:
            return
        # 恢复期间抑制补全面板与输入事件干扰
        self._suppress_palette = True
        try:
            loaded = sm.resume(self._agent, meta.session_id)
        except Exception as exc:  # noqa: BLE001
            self._suppress_palette = False
            self._toast("恢复失败", "err")
            self._chat_notice(f"恢复会话失败：{exc}")
            return

        # 先清空输入框（此时仍处于抑制状态，不会触发补全）
        try:
            field = self.query_one("#input", Input)
            field.value = ""
        except Exception:  # noqa: BLE001
            pass

        # 重建聊天区
        chat = self.query_one("#chat", VerticalScroll)
        chat.remove_children()
        self._last_compact_result = None
        self._session_id = sm.state.session_id
        for message in self._agent.history:
            role = message.get("role")
            content = message.get("content")
            if role == "user" and isinstance(content, str):
                chat.mount(UserMessage(content))
            elif role == "assistant" and isinstance(content, str) and content.strip():
                chat.mount(AssistantMessage(content))

        self._toast("会话已恢复", "ok")
        title = loaded.title if loaded else ""
        self._chat_notice(
            f"✓ 已恢复会话 {metadata_id(meta)}"
            + (f"「{title}」" if title else "")
            + f"\n共 {len(self._agent.history)} 条消息"
        )
        self._refresh_context()
        self._refresh_sidebar()
        self._scroll_end()

        # 清空输入框并恢复事件处理（先清空再解除抑制，避免触发补全）
        try:
            field = self.query_one("#input", Input)
            field.value = ""
            field.focus()
        except Exception:  # noqa: BLE001
            pass
        self._suppress_palette = False
        self._palette_open = False

    def _release_palette(self) -> None:
        self._suppress_palette = False
        self._palette_open = False

    def _show_sessions(self) -> None:
        sm = self._sessions
        if sm is None:
            self._chat_notice("会话管理未启用。")
            return
        metas = sm.list()
        if not metas:
            self._chat_notice("还没有保存过任何会话。")
            return
        lines = [f"共 {len(metas)} 个历史会话（新→旧）："]
        for meta in metas:
            lines.append("  " + meta.display())
        lines.append("\n输入 /resume 选择并恢复。")
        self._chat_notice("\n".join(lines))

    def _show_mcp(self) -> None:
        """显示 MCP 状态。"""
        mcp = self._mcp
        if mcp is None:
            self._chat_notice("未启用 MCP。")
            return
        statuses = getattr(mcp, "statuses", [])
        if not statuses:
            hint = "正在加载…" if self._mcp_loading else "未配置任何 MCP Server。"
            self._chat_notice(hint)
            return
        connected = sum(1 for s in statuses if s.connected)
        lines = [f"MCP Server：{connected}/{len(statuses)} 已连接"]
        for s in statuses:
            if s.connected:
                lines.append(f"  ● {s.name} — {s.tool_count} 个工具")
                for route in getattr(mcp, "routes", []):
                    if route.server == s.name:
                        lines.append(f"      · {route.exposed_name}")
            else:
                lines.append(f"  ○ {s.name} — {s.error}")
        self._chat_notice("\n".join(lines))

    def _show_context(self) -> None:
        usage = self._agent.context_usage()
        lines = [
            f"上下文占用：{usage.used} tokens",
            f"模型窗口：{usage.window} tokens{'（默认值）' if usage.window_is_default else ''}",
            f"占用比例：{usage.percent:.1f}%",
            f"预警阈值：{usage.warn_ratio * 100:.0f}%",
            f"数据来源：{'API usage' if usage.measured_by_api else '本地估算'}",
        ]
        if usage.needs_compact:
            lines.append("\n已达阈值，请执行 /compact。")
        self._chat_notice("\n".join(lines))

    def _show_last_compact(self) -> None:
        result = self._last_compact_result
        if result is None:
            self._chat_notice("本次会话还没有执行过压缩。")
            return
        self._show_compare(result)

    def _show_tools(self) -> None:
        specs = getattr(self._agent, "tool_specs", [])
        if not specs:
            self._chat_notice("尚未注册任何工具。")
            return
        lines = [f"已注册 {len(specs)} 个工具："]
        for i, item in enumerate(specs, 1):
            lines.append(f"{i}. {item['name']} — {item['description']}")
        self._chat_notice("\n".join(lines))

    def _show_skills(self) -> None:
        """列出已发现的 Skill（仅元信息，不含正文）。"""
        specs = self._skill_specs()
        if not specs:
            root = getattr(self._skills, "root", None)
            where = f"{root / '.agents' / 'skills'}" if root else ".agents/skills"
            self._chat_notice(f"未发现任何技能。\n扫描目录：{where}")
            return

        lines = [f"已发现 {len(specs)} 个技能（仅加载名称与描述）："]
        for i, item in enumerate(specs, 1):
            lines.append(f"{i}. {item['name']} — {item['description']}")

        errors = getattr(self._skills, "errors", [])
        if errors:
            lines.append("")
            lines.append("以下目录加载失败：")
            lines.extend(f"- {err}" for err in errors)
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
            self._refresh_context()
            if event.payload.get("context_warn"):
                self._toast("上下文已达 70%，请执行 /compact", "err")
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
        self._refresh_context()
        self._refresh_sidebar()
        self._scroll_end()

    def _refresh_context(self) -> None:
        """刷新顶栏的上下文计量。"""
        getter = getattr(self._agent, "context_usage", None)
        if not callable(getter):
            return
        try:
            usage = getter()
        except Exception:  # noqa: BLE001
            return
        try:
            self.query_one(ContextMeter).update_usage(usage, self._compacting)
        except Exception:  # noqa: BLE001 界面拆卸时忽略
            pass

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

    # ------------------------------------------------------------------ 压缩
    def action_compact(self) -> None:
        """执行 /compact：压缩上下文。"""
        if self._compacting:
            self._toast("已在压缩中，请稍候", "busy")
            return
        if self._busy:
            self._toast("正在生成中，请先等待或按 Esc 中断", "busy")
            return

        usage = self._agent.context_usage() if hasattr(self._agent, "context_usage") else None
        history = self._agent.history if hasattr(self._agent, "history") else []
        conversational = [m for m in history if m.get("role") != "system"]
        if not conversational:
            self._chat_notice("当前没有可压缩的对话内容。")
            return

        self._enter_compacting()
        self._compact_worker()

    def _enter_compacting(self) -> None:
        """进入压缩状态：禁用输入、禁用工具、更新界面。"""
        self._compacting = True
        if hasattr(self._agent, "set_compacting"):
            self._agent.set_compacting(True)
        self.query_one("#input", Input).disabled = True
        self.query_one(ContextMeter).update_usage(self._agent.context_usage(), True)
        self._refresh_sidebar()
        self._toast("正在压缩上下文…", "busy")
        self._chat_notice("⟳ 开始压缩上下文，归档原始记录并生成摘要…")

    def _exit_compacting(self, ok: bool, message: str) -> None:
        self._compacting = False
        if hasattr(self._agent, "set_compacting"):
            self._agent.set_compacting(False)
        self.query_one("#input", Input).disabled = False
        self.query_one("#input", Input).focus()
        self._refresh_context()
        self._refresh_sidebar()
        self._toast("就绪" if ok else "压缩失败", "ok" if ok else "err")
        self._chat_notice(message)

    @work(thread=True, exclusive=True)
    def _compact_worker(self) -> None:
        """后台执行压缩，避免阻塞界面。"""
        from core.context import CompactError, Compactor

        agent = self._agent
        try:
            compactor = Compactor(agent._client, self._project_root)
            messages = agent.history
            new_messages, result = compactor.compact(messages)
        except CompactError as exc:
            self.call_from_thread(
                self._exit_compacting, False,
                f"压缩失败：{exc}\n原有上下文已保留，可以修改后重新执行 /compact。",
            )
            return
        except Exception as exc:  # noqa: BLE001
            self.call_from_thread(
                self._exit_compacting, False,
                f"压缩失败（{type(exc).__name__}: {exc}）\n原有上下文已保留，可重新执行 /compact。",
            )
            return

        # 替换上下文（保留 System Prompt 与工具定义）
        agent.replace_context(new_messages)
        self.call_from_thread(self._show_compare, result)
        self.call_from_thread(
            self._exit_compacting, True,
            f"✓ 上下文压缩完成\n{result.describe()}\n\n"
            "已保留摘要与归档说明。需要更早的细节时可让模型调用 recallContext 检索。",
        )

    def _show_compare(self, result) -> None:
        """弹出压缩前后对比面板。"""
        from .screens.compact_compare import CompactCompareScreen

        self._last_compact_result = result
        try:
            self.push_screen(
                CompactCompareScreen(
                    result.before_text,
                    result.summary,
                    archive_id=result.archive_id,
                    before_tokens=result.before_tokens,
                    after_tokens=result.after_tokens,
                )
            )
        except Exception:  # noqa: BLE001 面板失败不应影响主流程
            pass

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
