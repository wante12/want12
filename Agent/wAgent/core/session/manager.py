"""会话管理：新建、保存、恢复，以及 AGENTS.md 的一次性注入。

UI 层只需要调用 SessionManager 的方法，不必关心 JSONL 细节。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .agents_md import build_injection_message, is_injected, load_agents_md
from .store import (
    SessionError,
    SessionMeta,
    list_sessions,
    load_session,
    next_session_id,
    save_session,
)


@dataclass
class SessionState:
    """当前会话状态。"""

    session_id: str
    created_at: str
    saved: bool = False
    agents_injected: bool = False

    def __repr__(self) -> str:
        return f"SessionState(id={self.session_id}, saved={self.saved})"


class SessionManager:
    """管理一个项目下的会话生命周期。"""

    def __init__(
        self,
        project_root: Path | str | None = None,
        subdir: str | None = None,
        agents_md_name: str = "AGENTS.md",
        autosave: bool = True,
    ) -> None:
        self._root = Path(project_root) if project_root else Path.cwd()
        self._subdir = subdir
        self._agents_md_name = agents_md_name
        self._autosave = autosave
        self._state = self._new_state()

    # ---------------------------------------------------------------- 状态
    def _new_state(self) -> SessionState:
        return SessionState(
            session_id=next_session_id(),
            created_at=datetime.now().isoformat(timespec="seconds"),
        )

    @property
    def state(self) -> SessionState:
        return self._state

    @property
    def project_root(self) -> Path:
        return self._root

    # ---------------------------------------------------------------- AGENTS.md
    def prepare_agents_md(self, agent) -> str | None:
        """把 AGENTS.md 注入 Agent 历史（仅首次）。

        返回注入内容的简短描述；没有 AGENTS.md 或已注入过则返回 None。
        """
        history = agent.history if hasattr(agent, "history") else []
        if is_injected(history):
            self._state.agents_injected = True
            return None

        agents = load_agents_md(self._root, self._agents_md_name)
        if agents is None:
            return None

        message = build_injection_message(agents)
        append = getattr(agent, "append_message", None)
        if callable(append):
            append(message)
        else:  # 兜底：直接操作内部历史
            agent._messages.append(message)

        self._state.agents_injected = True
        return f"已注入项目指令 {agents.path.name}（{len(agents.content)} 字符）"

    # ---------------------------------------------------------------- 保存
    def save(self, agent, session_id: str | None = None) -> Path:
        """保存当前会话，返回文件路径。"""
        messages = agent.history if hasattr(agent, "history") else []
        if not messages:
            raise SessionError("当前没有可保存的消息。")

        sid = session_id or self._state.session_id
        path = save_session(
            sid,
            messages,
            self._root,
            self._subdir,
            created_at=self._state.created_at if sid == self._state.session_id else None,
        )
        self._state.saved = True
        return path

    def autosave(self, agent) -> Path | None:
        """按配置决定是否自动保存；失败不抛异常。"""
        if not self._autosave:
            return None
        try:
            return self.save(agent)
        except SessionError:
            return None

    # ---------------------------------------------------------------- 新建
    def start_new(self) -> SessionState:
        """切换到新会话（不负责保存旧的，调用方先 autosave）。"""
        self._state = self._new_state()
        return self._state

    # ---------------------------------------------------------------- 恢复
    def list(self) -> list[SessionMeta]:
        return list_sessions(self._root, self._subdir)

    def resume(self, agent, session_id: str) -> SessionMeta | None:
        """把某个会话恢复到 Agent 里。

        会用会话内容替换当前上下文（保留 System Prompt）。
        """
        messages, meta = load_session(session_id, self._root, self._subdir)

        replace = getattr(agent, "replace_context", None)
        if callable(replace):
            replace(messages)
        else:  # 兜底
            agent._messages = list(messages)

        self._state = SessionState(
            session_id=session_id,
            created_at=(meta.created_at if meta else datetime.now().isoformat(timespec="seconds")),
            saved=True,
            agents_injected=is_injected(messages),
        )
        return meta


__all__ = ["SessionManager", "SessionState"]
