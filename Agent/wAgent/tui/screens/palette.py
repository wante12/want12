"""斜杠命令定义表与补全引导面板。

命令集中定义在 COMMANDS 里，供：
- 输入时的补全面板（输入 / 立即弹出候选）
- /help 面板
- 帮助文档保持一致
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static


@dataclass(frozen=True)
class Command:
    """一个斜杠命令。"""

    name: str
    summary: str
    usage: str = ""
    detail: str = ""

    @property
    def key(self) -> str:
        return self.name.lstrip("/")


#: 全部命令（顺序即补全面板的展示顺序）
COMMANDS: tuple[Command, ...] = (
    Command("/help", "打开帮助", detail="查看全部命令、快捷键与上下文管理说明"),
    Command("/new", "新建会话（自动保存当前会话）", usage="/new",
            detail="保存当前会话到 .agents/sessions，然后清空上下文开始新会话"),
    Command("/resume", "恢复历史会话", usage="/resume",
            detail="弹出会话列表，↑↓ 选择、回车恢复、Esc 取消"),
    Command("/save", "保存当前会话", usage="/save [名称]",
            detail="手动保存到 .agents/sessions；可选给会话起个名字"),
    Command("/sessions", "列出历史会话", detail="在对话区列出全部已保存会话"),
    Command("/compact", "压缩上下文", detail="归档原始记录并生成摘要，压缩期间禁用工具"),
    Command("/clear", "清空界面（保留历史）", detail="只清屏，不改变上下文"),
    Command("/reset", "重置上下文（等同 /new 但不保存）", detail="丢弃当前上下文重新开始"),
    Command("/tools", "列出已注册工具", detail="含本地工具与 MCP 工具"),
    Command("/skills", "列出已发现技能", detail="含加载失败的技能及原因"),
    Command("/mcp", "显示 MCP 服务器状态", detail="连接状态与每个服务器的工具"),
    Command("/cwd", "显示工作目录", detail="项目根目录（影响 .mcp.json 与 AGENTS.md 查找）"),
    Command("/model", "显示模型与配置", detail="模型名、接口地址、配置文件路径"),
    Command("/context", "显示上下文用量详情", detail="token 占用、窗口大小、阈值"),
    Command("/compact-preview", "查看上次压缩对比", detail="重新打开最近一次压缩的前后对比"),
    Command("/quit", "退出", detail="退出前可先 /save 保存会话"),
)


def names() -> list[str]:
    return [c.name for c in COMMANDS]


def find(prefix: str) -> list[Command]:
    """按前缀过滤命令，供补全面板使用。"""
    prefix = (prefix or "").strip().lower()
    if not prefix.startswith("/"):
        prefix = "/" + prefix
    return [c for c in COMMANDS if c.name.lower().startswith(prefix)]


def get(name: str) -> Command | None:
    name = (name or "").strip().lower()
    for c in COMMANDS:
        if c.name.lower() == name:
            return c
    return None


class CommandPalette(ModalScreen):
    """补全引导面板：方向键选择，回车补全，Esc 关闭。"""

    BINDINGS = [
        ("escape", "dismiss", "关闭"),
        ("up", "move(-1)", "上移"),
        ("down", "move(1)", "下移"),
        ("tab", "complete", "补全"),
        ("enter", "complete", "补全"),
    ]

    CSS = """
    CommandPalette {
        align: left bottom;
        background: #0d1117 40%;
    }

    #palette-box {
        width: 76;
        height: auto;
        max-height: 70%;
        background: #010409;
        border: round #58a6ff;
        padding: 0 1 0 1;
        margin: 0 0 3 2;
    }

    #palette-title {
        height: 1;
        color: #58a6ff;
        text-style: bold;
    }

    #palette-list {
        height: auto;
        max-height: 20;
    }

    .palette-item {
        height: 1;
        padding: 0 1 0 1;
        color: #c9d1d9;
    }

    .palette-item.selected {
        background: #1f6feb;
        color: #ffffff;
        text-style: bold;
    }

    #palette-hint {
        height: 1;
        color: #6e7681;
    }
    """

    def __init__(self, prefix: str = "/", **kwargs) -> None:
        super().__init__(**kwargs)
        self._prefix = prefix or "/"
        self._items = find(self._prefix) or list(COMMANDS)
        self._index = 0
        self._selected: str | None = None

    # ---------------------------------------------------------------- 布局
    def compose(self) -> ComposeResult:
        with VerticalScroll(id="palette-box"):
            yield Static(f"命令补全 · 输入前缀 {self._prefix}", id="palette-title")
            with VerticalScroll(id="palette-list"):
                for i, cmd in enumerate(self._items):
                    yield Static(self._line(cmd), classes="palette-item", id=f"cmd-{i}")
            yield Static("↑↓ 选择 · Enter/Tab 补全 · Esc 取消", id="palette-hint")

    @staticmethod
    def _line(cmd: Command) -> str:
        return f"{cmd.name:<18} {cmd.summary}"

    def on_mount(self) -> None:
        self._highlight()

    def _highlight(self) -> None:
        for i in range(len(self._items)):
            try:
                widget = self.query_one(f"#cmd-{i}", Static)
                widget.set_class(i == self._index, "selected")
            except Exception:  # noqa: BLE001
                pass

    # ---------------------------------------------------------------- 交互
    def action_move(self, delta: int) -> None:
        if not self._items:
            return
        self._index = (self._index + delta) % len(self._items)
        self._highlight()

    def action_complete(self) -> None:
        if 0 <= self._index < len(self._items):
            self._selected = self._items[self._index].name
            self.dismiss(self._selected)
        else:
            self.dismiss(None)

    def action_dismiss(self, result=None) -> None:
        self._selected = None
        self.dismiss(None)

    @property
    def selected(self) -> str | None:
        return self._selected


__all__ = [
    "COMMANDS",
    "Command",
    "CommandPalette",
    "find",
    "get",
    "names",
]
