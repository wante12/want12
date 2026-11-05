"""会话持久化：保存、列出、恢复。

目录：<项目根>/.agents/sessions/
文件：<会话编号>.jsonl

格式与上下文归档一致（JSONL，一行一条消息），
这样「会话事件日志」既是恢复来源，也天然是 AGENTS.md 的持久化位置。

首行是 meta，记录会话创建时间、标题、消息数等。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

#: 默认会话目录（可被 config.ini 的 [session] dir 覆盖）
SESSION_DIR = Path(".agents") / "sessions"


class SessionError(Exception):
    """会话读写失败。"""


@dataclass
class SessionMeta:
    """会话摘要信息，用于列表展示。"""

    session_id: str
    title: str = ""
    created_at: str = ""
    updated_at: str = ""
    message_count: int = 0
    path: Path | None = None

    def display(self) -> str:
        title = self.title or "(无标题)"
        if len(title) > 48:
            title = title[:48] + "…"
        stamp = (self.updated_at or self.created_at or "")[:16].replace("T", " ")
        return f"{self.session_id}  {stamp}  {self.message_count:>3} 条  {title}"


def sessions_dir(project_root: Path | str | None = None, subdir: str | Path | None = None) -> Path:
    root = Path(project_root) if project_root else Path.cwd()
    return root / (Path(subdir) if subdir else SESSION_DIR)


def new_session_id(now: datetime | None = None) -> str:
    """生成会话编号 YYYYMMDD-HHMMSS。"""
    stamp = now or datetime.now()
    return stamp.strftime("%Y%m%d-%H%M%S")


def unique_session_id(
    project_root: Path | str | None = None,
    subdir: str | Path | None = None,
    now: datetime | None = None,
) -> str:
    """生成在目录中唯一的会话编号。

    同一秒内多次调用时追加 -1、-2 后缀，保证不冲突。
    """
    base = new_session_id(now)
    directory = sessions_dir(project_root, subdir)
    candidate = base
    suffix = 1
    while (directory / f"{candidate}.jsonl").exists():
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate


#: 记录进程内已发放的编号，避免同一秒内重复
_ISSUED: set[str] = set()


def next_session_id() -> str:
    """进程内保证不重复的会话编号（用于「新建会话」按钮）。"""
    stamp = datetime.now()
    candidate = stamp.strftime("%Y%m%d-%H%M%S")
    suffix = 1
    base = candidate
    while candidate in _ISSUED:
        candidate = f"{base}-{suffix}"
        suffix += 1
    _ISSUED.add(candidate)
    return candidate


def session_path(
    session_id: str,
    project_root: Path | str | None = None,
    subdir: str | Path | None = None,
) -> Path:
    return sessions_dir(project_root, subdir) / f"{session_id}.jsonl"


def _message_title(messages: list[dict[str, Any]]) -> str:
    """取第一条用户消息作为标题。"""
    for message in messages:
        if message.get("role") == "user":
            text = message.get("content")
            if isinstance(text, str) and text.strip():
                first_line = text.strip().splitlines()[0]
                return first_line[:80]
    return ""


def save_session(
    session_id: str,
    messages: list[dict[str, Any]],
    project_root: Path | str | None = None,
    subdir: str | Path | None = None,
    created_at: str | None = None,
    title: str | None = None,
) -> Path:
    """把消息写入会话文件。返回路径；失败抛 SessionError。"""
    if not messages:
        raise SessionError("没有可保存的消息。")

    path = session_path(session_id, project_root, subdir)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".jsonl.tmp")
        now = datetime.now().isoformat(timespec="seconds")

        with tmp.open("w", encoding="utf-8", newline="\n") as fh:
            meta = {
                "type": "meta",
                "session_id": session_id,
                "title": title if title is not None else _message_title(messages),
                "created_at": created_at or now,
                "updated_at": now,
                "message_count": len(messages),
            }
            fh.write(json.dumps(meta, ensure_ascii=False) + "\n")

            for index, message in enumerate(messages):
                record = {
                    "seq": index,
                    "role": message.get("role", ""),
                    "content": message.get("content"),
                }
                if message.get("tool_calls"):
                    record["tool_calls"] = message["tool_calls"]
                if message.get("tool_call_id"):
                    record["tool_call_id"] = message["tool_call_id"]
                if message.get("name"):
                    record["name"] = message["name"]
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")

        tmp.replace(path)
    except OSError as exc:
        raise SessionError(f"保存会话失败 {path}：{exc}") from exc

    return path


def load_session(
    session_id: str,
    project_root: Path | str | None = None,
    subdir: str | Path | None = None,
) -> tuple[list[dict[str, Any]], SessionMeta | None]:
    """读取会话。返回 (消息列表, 元信息)。"""
    path = session_path(session_id, project_root, subdir)
    if not path.is_file():
        raise SessionError(f"找不到会话：{session_id}")

    messages: list[dict[str, Any]] = []
    meta: SessionMeta | None = None

    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if record.get("type") == "meta":
                    meta = SessionMeta(
                        session_id=str(record.get("session_id", session_id)),
                        title=str(record.get("title", "")),
                        created_at=str(record.get("created_at", "")),
                        updated_at=str(record.get("updated_at", "")),
                        message_count=int(record.get("message_count", 0)),
                        path=path,
                    )
                    continue
                message = {"role": record.get("role", ""), "content": record.get("content")}
                if record.get("tool_calls"):
                    message["tool_calls"] = record["tool_calls"]
                if record.get("tool_call_id"):
                    message["tool_call_id"] = record["tool_call_id"]
                if record.get("name"):
                    message["name"] = record["name"]
                messages.append(message)
    except OSError as exc:
        raise SessionError(f"读取会话失败 {path}：{exc}") from exc

    return messages, meta


def list_sessions(
    project_root: Path | str | None = None,
    subdir: str | Path | None = None,
) -> list[SessionMeta]:
    """列出所有会话，按更新时间从新到旧。"""
    directory = sessions_dir(project_root, subdir)
    if not directory.is_dir():
        return []

    metas: list[SessionMeta] = []
    try:
        files = list(directory.glob("*.jsonl"))
    except OSError:
        return []

    for path in files:
        meta = SessionMeta(session_id=path.stem, path=path)
        try:
            with path.open("r", encoding="utf-8") as fh:
                first = fh.readline().strip()
            if first:
                record = json.loads(first)
                if record.get("type") == "meta":
                    meta.title = str(record.get("title", ""))
                    meta.created_at = str(record.get("created_at", ""))
                    meta.updated_at = str(record.get("updated_at", ""))
                    meta.message_count = int(record.get("message_count", 0))
        except (OSError, json.JSONDecodeError):
            pass
        metas.append(meta)

    metas.sort(key=lambda m: (m.session_id, m.updated_at or m.created_at), reverse=True)
    return metas


def delete_session(
    session_id: str,
    project_root: Path | str | None = None,
    subdir: str | Path | None = None,
) -> bool:
    path = session_path(session_id, project_root, subdir)
    if not path.is_file():
        return False
    try:
        path.unlink()
        return True
    except OSError:
        return False


__all__ = [
    "SESSION_DIR",
    "SessionError",
    "SessionMeta",
    "delete_session",
    "list_sessions",
    "load_session",
    "new_session_id",
    "save_session",
    "session_path",
    "sessions_dir",
]
