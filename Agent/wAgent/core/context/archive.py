"""原始上下文的归档与检索。

目录：<项目根>/.agents/context/
文件：<归档编号>.jsonl   例如 20261022-153000.jsonl

每行是一条消息的完整记录：
    {"seq": 0, "role": "user", "content": "...", "tool_calls": [...], "tool_call_id": "..."}

用 JSONL 而不是单个 JSON 数组，是为了：
- 追加写入方便、出错时不会破坏整个文件
- 检索时可以逐行读取，不必一次性载入全部内容
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

#: 相对项目根的默认归档目录（可被 config.ini 的 [context] archive_dir 覆盖）
CONTEXT_DIR = Path(".agents") / "context"
#: 归档编号格式：日期-时间
ID_PATTERN = re.compile(r"^\d{8}-\d{6}$")
#: 单条记录里 content 的默认最大保存长度
MAX_CONTENT_CHARS = 200_000


class ArchiveError(Exception):
    """归档读写失败。"""


def generate_id(now: datetime | None = None) -> str:
    """生成归档编号，如 20261022-153000。"""
    stamp = now or datetime.now()
    return stamp.strftime("%Y%m%d-%H%M%S")


def context_dir(
    project_root: Path | str | None = None,
    subdir: str | Path | None = None,
) -> Path:
    """归档目录。subdir 可来自配置，默认 .agents/context。"""
    root = Path(project_root) if project_root else Path.cwd()
    return root / (Path(subdir) if subdir else CONTEXT_DIR)


def archive_path(
    archive_id: str,
    project_root: Path | str | None = None,
    subdir: str | Path | None = None,
) -> Path:
    if not ID_PATTERN.match(archive_id or ""):
        raise ArchiveError(f"归档编号格式不正确：{archive_id}（应为 YYYYMMDD-HHMMSS）")
    return context_dir(project_root, subdir) / f"{archive_id}.jsonl"


def _truncate(text: str, limit: int = MAX_CONTENT_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n…（该条原文过长，已截断，原始长度 {len(text)} 字符）"


def save_archive(
    archive_id: str,
    messages: list[dict[str, Any]],
    project_root: Path | str | None = None,
    meta: dict[str, Any] | None = None,
    subdir: str | Path | None = None,
    max_content_chars: int = MAX_CONTENT_CHARS,
) -> Path:
    """把消息原样写入归档文件。

    返回文件路径；失败时抛 ArchiveError（调用方必须中止压缩）。
    """
    path = archive_path(archive_id, project_root, subdir)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ArchiveError(f"无法创建归档目录 {path.parent}：{exc}") from exc

    tmp = path.with_suffix(".jsonl.tmp")
    try:
        with tmp.open("w", encoding="utf-8", newline="\n") as fh:
            # 第一行是元信息，便于后续区分
            header = {"type": "meta", "archive_id": archive_id,
                      "created_at": datetime.now().isoformat(timespec="seconds"),
                      "message_count": len(messages)}
            if meta:
                header.update(meta)
            fh.write(json.dumps(header, ensure_ascii=False) + "\n")

            for index, message in enumerate(messages):
                record = {
                    "seq": index,
                    "role": message.get("role", ""),
                    "content": _truncate(_stringify(message.get("content")), max_content_chars),
                }
                if message.get("tool_calls"):
                    record["tool_calls"] = message["tool_calls"]
                if message.get("tool_call_id"):
                    record["tool_call_id"] = message["tool_call_id"]
                if message.get("name"):
                    record["name"] = message["name"]
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")

        # 原子替换，避免写到一半留下残缺文件
        tmp.replace(path)
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        raise ArchiveError(f"写入归档失败 {path}：{exc}") from exc

    if not path.is_file() or path.stat().st_size == 0:
        raise ArchiveError(f"归档文件写入后为空：{path}")
    return path


def _stringify(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    return json.dumps(content, ensure_ascii=False)


def read_archive(
    archive_id: str,
    project_root: Path | str | None = None,
    subdir: str | Path | None = None,
) -> list[dict[str, Any]]:
    path = archive_path(archive_id, project_root, subdir)
    if not path.is_file():
        raise ArchiveError(f"找不到归档：{archive_id}")
    records: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue  # 单行损坏不影响其余内容
    except OSError as exc:
        raise ArchiveError(f"读取归档失败 {path}：{exc}") from exc
    return records


def list_archives(
    project_root: Path | str | None = None,
    subdir: str | Path | None = None,
) -> list[str]:
    """列出所有归档编号，按时间从新到旧。"""
    directory = context_dir(project_root, subdir)
    if not directory.is_dir():
        return []
    try:
        names = [
            p.stem for p in directory.glob("*.jsonl") if ID_PATTERN.match(p.stem)
        ]
    except OSError:
        return []
    return sorted(names, reverse=True)


def iter_records(
    archive_id: str,
    project_root: Path | str | None = None,
    subdir: str | Path | None = None,
) -> Iterator[dict[str, Any]]:
    for record in read_archive(archive_id, project_root, subdir):
        if record.get("type") == "meta":
            continue
        yield record


__all__ = [
    "CONTEXT_DIR",
    "ID_PATTERN",
    "ArchiveError",
    "archive_path",
    "context_dir",
    "generate_id",
    "iter_records",
    "list_archives",
    "read_archive",
    "save_archive",
]
