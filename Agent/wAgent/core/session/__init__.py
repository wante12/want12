"""会话子系统。

    store.py      会话文件读写（JSONL）
    agents_md.py  AGENTS.md 一次注入
    manager.py    SessionManager：新建 / 保存 / 恢复
"""

from .agents_md import (
    AGENTS_FILE,
    INJECTION_MARKER,
    AgentsMd,
    build_injection_message,
    find_agents_md,
    is_injected,
    load_agents_md,
)
from .manager import SessionManager, SessionState
from .store import (
    SESSION_DIR,
    SessionError,
    SessionMeta,
    delete_session,
    list_sessions,
    load_session,
    new_session_id,
    save_session,
    session_path,
    sessions_dir,
)

__all__ = [
    "AGENTS_FILE",
    "INJECTION_MARKER",
    "SESSION_DIR",
    "AgentsMd",
    "SessionError",
    "SessionManager",
    "SessionMeta",
    "SessionState",
    "build_injection_message",
    "delete_session",
    "find_agents_md",
    "is_injected",
    "list_sessions",
    "load_agents_md",
    "load_session",
    "new_session_id",
    "save_session",
    "session_path",
    "sessions_dir",
]
