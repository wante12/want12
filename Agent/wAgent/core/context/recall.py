"""历史上下文检索：在归档文件里做本地全文关键词匹配。

不依赖向量库或 Embedding：
    1. 把用户给的关键词按空白/标点切分
    2. 逐行扫描归档 JSONL，统计每个片段的命中次数
    3. 按命中数排序，取前 N 段返回

重点控制返回长度——检索结果如果太长，等于又把上下文撑满了。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .archive import ArchiveError, iter_records, list_archives
from ..tools.base import Tool

#: 默认返回片段数上限（config.ini 的 [context] recall_max_snippets 可覆盖）
MAX_SNIPPETS = 6
#: 单个片段的默认最大字符数
SNIPPET_CHARS = 400
#: 检索结果总长度默认上限，避免再次占满上下文
MAX_TOTAL_CHARS = 4000
#: 分割关键词用的分隔符
_SPLIT_RE = re.compile(r"[\s,，。;；、/|]+")


@dataclass
class Match:
    archive_id: str
    seq: int
    role: str
    score: int
    snippet: str


def split_keywords(text: str) -> list[str]:
    """把查询文本切成关键词，过滤空串与单字符噪声。"""
    parts = [p.strip() for p in _SPLIT_RE.split(text or "")]
    keywords = [p for p in parts if p]
    if not keywords and (text or "").strip():
        keywords = [(text or "").strip()]
    return keywords


def _make_snippet(text: str, keywords: list[str], limit: int = SNIPPET_CHARS) -> str:
    """截取命中位置附近的一段文字。"""
    lowered = text.lower()
    position = -1
    for kw in keywords:
        idx = lowered.find(kw.lower())
        if idx >= 0 and (position < 0 or idx < position):
            position = idx

    if position < 0:
        snippet = text[:limit]
    else:
        start = max(0, position - limit // 3)
        snippet = text[start:start + limit]
        if start > 0:
            snippet = "…" + snippet

    if len(text) > len(snippet) and not snippet.endswith("…"):
        snippet = snippet.rstrip() + "…"
    return " ".join(snippet.split())


def search_archive(
    archive_id: str,
    keywords: list[str],
    project_root: Path | str | None = None,
    subdir: str | Path | None = None,
    snippet_chars: int = SNIPPET_CHARS,
) -> list[Match]:
    """在单个归档里检索。"""
    matches: list[Match] = []
    try:
        records = list(iter_records(archive_id, project_root, subdir))
    except ArchiveError:
        return matches

    for record in records:
        content = str(record.get("content", ""))
        extra = ""
        if record.get("tool_calls"):
            import json

            extra = json.dumps(record["tool_calls"], ensure_ascii=False)
        haystack = f"{content}\n{extra}".lower()

        score = sum(haystack.count(kw.lower()) for kw in keywords)
        if score <= 0:
            continue

        matches.append(
            Match(
                archive_id=archive_id,
                seq=int(record.get("seq", -1)),
                role=str(record.get("role", "")),
                score=score,
                snippet=_make_snippet(content or extra, keywords),
            )
        )
    return matches


def render_matches(
    matches: list[Match], query: str, max_total_chars: int = MAX_TOTAL_CHARS
) -> str:
    """把命中结果渲染成给 LLM 的文本，总长度受控。"""
    if not matches:
        return f'未在归档中找到与「{query}」相关的内容。'

    lines = [f'找到 {len(matches)} 处与「{query}」相关的记录（按相关度排序）：', ""]
    used = 0
    shown = 0

    for match in matches:
        block = (
            f"[{shown + 1}] 归档 {match.archive_id} · 第 {match.seq} 条 · {match.role}"
            f"（命中 {match.score} 次）\n{match.snippet}"
        )
        if used + len(block) > max_total_chars:
            lines.append(f"…（已达返回上限，还有 {len(matches) - shown} 条未显示）")
            break
        lines.append(block)
        lines.append("")
        used += len(block)
        shown += 1

    return "\n".join(lines).rstrip()


class RecallContextTool(Tool):
    name = "recallContext"
    description = (
        "检索被压缩的历史上下文归档。当上下文压缩摘要中缺少某些历史细节时使用。"
        "id 可选：指定归档编号则只查该归档；不指定则在所有历史归档中检索。"
        "text 必需：要查找的关键词或文本内容。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "要搜索的关键词或文本，多个词用空格分隔",
            },
            "id": {
                "type": "string",
                "description": "可选。归档编号，如 20261022-153000；不填则检索所有归档",
            },
        },
        "required": ["text"],
        "additionalProperties": False,
    }

    def __init__(self, project_root: Path | str | None = None, settings=None) -> None:
        self._project_root = Path(project_root) if project_root else None
        self._settings = settings

    def _cfg(self, name: str, default):
        return getattr(self._settings, name, default) if self._settings else default

    def run(self, text: str, id: str | None = None) -> str:  # noqa: A002 参数名按需求
        query = (text or "").strip()
        if not query:
            return "检索失败：text 不能为空。"

        keywords = split_keywords(query)
        if not keywords:
            return f"检索失败：无法从「{query}」中提取关键词。"

        subdir = self._cfg("archive_dir", None)
        snippet_chars = self._cfg("recall_snippet_chars", SNIPPET_CHARS)
        max_total = self._cfg("recall_max_total_chars", MAX_TOTAL_CHARS)
        max_snippets = self._cfg("recall_max_snippets", MAX_SNIPPETS)

        archive_id = (id or "").strip() or None

        if archive_id:
            archives = [archive_id]
            try:
                from .archive import archive_path

                path = archive_path(archive_id, self._project_root, subdir)
            except ArchiveError as exc:
                return f"检索失败：{exc}"
            if not path.is_file():
                available = list_archives(self._project_root, subdir)
                hint = "、".join(available[:5]) if available else "（无归档）"
                return f"检索失败：找不到归档 {archive_id}。现有归档：{hint}"
        else:
            archives = list_archives(self._project_root, subdir)
            if not archives:
                return (
                    "检索失败：还没有任何上下文归档。"
                    "归档会在执行 /compact 压缩上下文时自动生成。"
                )

        all_matches: list[Match] = []
        for item in archives:
            all_matches.extend(
                search_archive(
                    item,
                    keywords,
                    self._project_root,
                    subdir=subdir,
                    snippet_chars=snippet_chars,
                )
            )

        if not all_matches:
            scope = f"归档 {archive_id}" if archive_id else f"{len(archives)} 个归档"
            return f'未在{scope}中找到与「{query}」相关的内容。'

        # 相关度优先；同分时归档编号大的（较新的）优先
        # 归档编号是 YYYYMMDD-HHMMSS，字典序即时间序
        all_matches.sort(key=lambda m: m.archive_id, reverse=True)
        all_matches.sort(key=lambda m: -m.score)

        return render_matches(all_matches[:max_snippets], query, max_total)


def build_recall_tool(
    project_root: Path | str | None = None, settings=None
) -> Tool:
    return RecallContextTool(project_root, settings)


__all__ = [
    "MAX_SNIPPETS",
    "MAX_TOTAL_CHARS",
    "Match",
    "RecallContextTool",
    "SNIPPET_CHARS",
    "build_recall_tool",
    "render_matches",
    "search_archive",
    "split_keywords",
]
