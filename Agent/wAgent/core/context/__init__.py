"""上下文管理子系统。

    tokens.py     Token 估算与模型窗口表
    archive.py    原始上下文归档（JSONL）
    compactor.py  压缩流程与专用 Prompt
    recall.py     recallContext 检索工具
    usage.py      当前上下文用量统计（供 UI 显示与阈值判断）
"""

from .archive import (
    CONTEXT_DIR,
    ArchiveError,
    archive_path,
    context_dir,
    generate_id,
    list_archives,
    read_archive,
    save_archive,
)
from .compactor import (
    ARCHIVE_NOTICE,
    COMPACT_PROMPT,
    CompactError,
    CompactResult,
    Compactor,
)
from .recall import RecallContextTool, build_recall_tool
from .tokens import (
    DEFAULT_CONTEXT_WINDOW,
    MODEL_CONTEXT_WINDOWS,
    context_window_for,
    count_messages_tokens,
    count_text_tokens,
    count_tools_tokens,
    format_k,
)
from .usage import ContextUsage

__all__ = [
    "ARCHIVE_NOTICE",
    "COMPACT_PROMPT",
    "CONTEXT_DIR",
    "DEFAULT_CONTEXT_WINDOW",
    "MODEL_CONTEXT_WINDOWS",
    "ArchiveError",
    "CompactError",
    "CompactResult",
    "Compactor",
    "ContextUsage",
    "RecallContextTool",
    "archive_path",
    "build_recall_tool",
    "context_dir",
    "context_window_for",
    "count_messages_tokens",
    "count_text_tokens",
    "count_tools_tokens",
    "format_k",
    "generate_id",
    "list_archives",
    "read_archive",
    "save_archive",
]
