"""内置工具：文件系统操作（9 个）。

全部用 Python 标准库实现（pathlib / os / shutil），不调用外部命令：
中文路径、空格路径与错误类型都比 shell 更可控。

工具清单：
    getCwd       获取当前工作目录
    listDir      列出目录下的文件与子目录
    getFileType  获取文件类型（扩展名 / MIME / 文本或二进制）
    readFile     读取纯文本文件内容
    createFile   按目录 + 文件名创建新文件
    editFile     编辑纯文本文件（overwrite / append）
    createDir    创建目录
    deleteDir    删除目录（含非空目录）
    deleteFile   删除文件

安全说明：
    不设目录白名单，路径以运行 Agent 的用户权限为准。
    但删除类操作会拒绝文件系统根目录、当前工作目录及其上级目录。
"""

from __future__ import annotations

import contextvars
import mimetypes
import os
import shutil
from pathlib import Path
from typing import Any

from ..config import FsSettings
from .base import Tool

# 判定文本文件时探测的字节数
_SNIFF_BYTES = 8192

# 文本解码候选顺序（与 cli.py 保持一致，兼容中文环境）
_ENCODINGS = ("utf-8", "gbk", "latin-1")

#: 当前生效的允许根目录。由 build_fs_tools() 设置，_resolve() 据此做沙箱校验。
#: 为空列表表示不限制（保持向后兼容）。
_ALLOWED_ROOTS: contextvars.ContextVar[list[Path]] = contextvars.ContextVar(
    "fs_allowed_roots", default=[]
)
#: 是否要求覆盖写入必须显式确认
_REQUIRE_CONFIRM: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "fs_require_confirm", default=True
)


def reset_sandbox() -> None:
    """清空沙箱设置，恢复「不限制」的默认行为。

    测试用例之间必须调用，否则上一个用例的 allowed_roots 会泄漏到下一个。
    """
    _ALLOWED_ROOTS.set([])
    _REQUIRE_CONFIRM.set(True)


# ====================================================================== 辅助
def _human_size(num: int) -> str:
    value = float(num)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{num} B"


class SandboxError(Exception):
    """路径超出允许范围。"""


def _resolve(raw: str) -> Path:
    """把用户给的路径转成绝对路径（不要求已存在）。

    若配置了 [fs] allowed_roots，则校验解析后的路径必须落在其中。
    所有文件工具都经过这里，因此沙箱是统一的。
    """
    path = Path(os.path.expandvars(raw)).expanduser().resolve()

    roots = _ALLOWED_ROOTS.get()
    if roots:
        error = _check_sandbox(path, roots)
        if error:
            raise SandboxError(error)
    return path


def _is_binary(path: Path) -> bool:
    """用「前若干字节是否含 NUL」判断是否二进制，简单可靠。"""
    try:
        chunk = path.open("rb").read(_SNIFF_BYTES)
    except OSError:
        return True
    if not chunk:
        return False
    if b"\x00" in chunk:
        return True
    # 无法以 UTF-8 或 GBK 解码时也视为二进制
    for enc in ("utf-8", "gbk"):
        try:
            chunk.decode(enc)
            return False
        except UnicodeDecodeError:
            continue
    return True


def _read_text(path: Path) -> tuple[str, str]:
    """读取文本文件，返回 (内容, 实际编码)。"""
    raw = path.read_bytes()
    for enc in _ENCODINGS:
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace"), "utf-8(有损)"


def _guard_destructive(target: Path) -> str | None:
    """删除类操作的兜底保护。返回错误信息，或 None 表示可执行。"""
    anchor = Path(target.anchor) if target.anchor else None
    if anchor and target == anchor:
        return f"拒绝删除文件系统根目录：{target}"
    try:
        cwd = Path.cwd().resolve()
    except OSError:
        return None
    if target == cwd:
        return f"拒绝删除当前工作目录：{target}"
    if target in cwd.parents:
        return f"拒绝删除当前工作目录的上级目录：{target}"
    return None


# ====================================================================== 沙箱
def _parse_roots(raw: Any) -> list[Path]:
    """把配置里的允许根目录解析成绝对路径列表。

    支持字符串（分号/逗号分隔）或数组。
    """
    if not raw:
        return []
    if isinstance(raw, str):
        parts = [p for p in raw.replace(";", ",").split(",")]
    elif isinstance(raw, (list, tuple)):
        parts = list(raw)
    else:
        return []

    roots: list[Path] = []
    for item in parts:
        text = str(item).strip()
        if not text:
            continue
        try:
            roots.append(Path(os.path.expandvars(text)).expanduser().resolve())
        except OSError:
            continue
    return roots


def _check_sandbox(target: Path, roots: list[Path]) -> str | None:
    """检查路径是否落在允许的根目录内。返回错误信息或 None。

    roots 为空表示不做限制（默认行为，保持向后兼容）。
    """
    if not roots:
        return None

    try:
        resolved = target.resolve()
    except OSError:
        return f"拒绝访问：无法解析路径 {target}"

    for root in roots:
        if resolved == root or root in resolved.parents:
            return None

    allowed = "、".join(str(r) for r in roots)
    return (
        f"拒绝访问：{resolved} 不在允许的目录范围内。\n"
        f"允许的根目录：{allowed}\n"
        "如需放开，请在 config.ini 的 [fs] allowed_roots 中追加该目录。"
    )


def _require_exists(path: Path, kinds: str = "文件或目录") -> str | None:
    if not path.exists():
        return f"路径不存在：{path}"
    return None


def _safe_resolve(raw: str) -> Path | str:
    """带沙箱校验的路径解析。

    返回 Path 表示通过；返回 str 表示被拒绝，内容即错误信息，
    工具方法直接 return 该字符串即可。
    """
    try:
        return _resolve(raw)
    except SandboxError as exc:
        return str(exc)
    except OSError as exc:
        return f"路径解析失败：{raw}（{exc}）"


# ====================================================================== 工具
class GetCwdTool(Tool):
    name = "getCwd"
    description = "获取当前工作目录（所有相对路径的基准目录）。"
    parameters = {"type": "object", "properties": {}, "additionalProperties": False}

    def run(self) -> str:
        try:
            return f"当前工作目录：{Path.cwd()}"
        except OSError as exc:
            return f"获取工作目录失败：{exc}"


class ListDirTool(Tool):
    name = "listDir"
    description = (
        "列出指定目录下的文件与子目录，包含类型和大小。"
        "path 省略时使用当前工作目录；recursive=True 时递归列出全部层级。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "目录路径，默认为当前工作目录"},
            "recursive": {"type": "boolean", "description": "是否递归列出子目录，默认 false"},
        },
        "additionalProperties": False,
    }

    def __init__(self, settings: FsSettings | None = None) -> None:
        self._settings = settings or FsSettings()

    def run(self, path: str = ".", recursive: bool = False) -> str:
        target = _safe_resolve(path or ".")
        if isinstance(target, str):
            return target
        if not target.exists():
            return f"列目录失败：路径不存在 {target}"
        if not target.is_dir():
            return f"列目录失败：不是目录 {target}"

        try:
            if recursive:
                entries = sorted(target.rglob("*"))
            else:
                entries = sorted(target.iterdir())
        except OSError as exc:
            return f"列目录失败：{exc}"

        limit = self._settings.max_list_entries
        total = len(entries)
        shown = entries[:limit]

        lines = [f"目录：{target}（共 {total} 项）"]
        if not shown:
            lines.append("  (空目录)")
        for item in shown:
            try:
                is_dir = item.is_dir()
                size = "" if is_dir else f"  {_human_size(item.stat().st_size)}"
            except OSError:
                is_dir, size = False, "  (无法读取)"
            rel = item.relative_to(target).as_posix()  # 统一用 /，Windows 下也好看
            label = "[目录]" if is_dir else "[文件]"
            lines.append(f"  {label}  {rel}{'/' if is_dir else ''}{size}")

        if total > limit:
            lines.append(f"…（仅显示前 {limit} 项，共 {total} 项）")
        return "\n".join(lines)


class GetFileTypeTool(Tool):
    name = "getFileType"
    description = "获取文件类型：扩展名、MIME 类型、是否纯文本、大小。"
    parameters = {
        "type": "object",
        "properties": {"path": {"type": "string", "description": "文件路径"}},
        "required": ["path"],
        "additionalProperties": False,
    }

    def run(self, path: str) -> str:
        if not (path or "").strip():
            return "获取文件类型失败：path 不能为空。"
        target = _safe_resolve(path)
        if isinstance(target, str):
            return target
        if not target.exists():
            return f"获取文件类型失败：文件不存在 {target}"
        if target.is_dir():
            return f"获取文件类型失败：这是目录，不是文件 {target}"

        try:
            size = target.stat().st_size
        except OSError as exc:
            return f"获取文件类型失败：{exc}"

        suffix = target.suffix.lower()
        mime, _ = mimetypes.guess_type(target.name)
        binary = _is_binary(target)

        lines = [
            f"文件：{target}",
            f"名称：{target.name}",
            f"扩展名：{suffix or '(无)'}",
            f"MIME：{mime or '(未知)'}",
            f"类型：{'二进制' if binary else '纯文本'}",
            f"大小：{_human_size(size)}（{size} 字节）",
        ]
        if binary:
            lines.append("可用工具：二进制文件不支持 readFile / editFile")
        else:
            lines.append("可用工具：readFile 读取、editFile 编辑")
        return "\n".join(lines)


class ReadFileTool(Tool):
    name = "readFile"
    description = "读取纯文本文件的完整内容。不支持二进制文件（先用 getFileType 判断）。"
    parameters = {
        "type": "object",
        "properties": {"path": {"type": "string", "description": "文件路径"}},
        "required": ["path"],
        "additionalProperties": False,
    }

    def __init__(self, settings: FsSettings | None = None) -> None:
        self._settings = settings or FsSettings()

    def run(self, path: str) -> str:
        if not (path or "").strip():
            return "读取失败：path 不能为空。"
        target = _safe_resolve(path)
        if isinstance(target, str):
            return target
        if not target.exists():
            return f"读取失败：文件不存在 {target}"
        if target.is_dir():
            return f"读取失败：这是目录，请改用 listDir。路径：{target}"

        if _is_binary(target):
            return (
                f"读取失败：{target.name} 是二进制文件，readFile 只支持纯文本。"
                "可先用 getFileType 确认类型。"
            )

        try:
            text, encoding = _read_text(target)
        except OSError as exc:
            return f"读取失败：{exc}"

        line_count = text.count("\n") + (1 if text and not text.endswith("\n") else 0)
        limit = self._settings.max_read_chars
        truncated = False
        if len(text) > limit:
            text = text[:limit]
            truncated = True

        header = f"文件：{target}（{line_count} 行，{encoding}）"
        footer = f"\n\n…（内容过长，已截断，仅返回前 {limit} 字符）" if truncated else ""
        return f"{header}\n\n{text}{footer}"


class CreateFileTool(Tool):
    name = "createFile"
    description = (
        "在指定目录下按文件名创建新的纯文本文件。"
        "目标文件已存在时报错，不会覆盖；目录必须已存在（可先用 createDir 创建）。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "directory": {"type": "string", "description": "文件所在目录"},
            "filename": {"type": "string", "description": "文件名（可含扩展名）"},
            "content": {"type": "string", "description": "初始内容，默认空"},
        },
        "required": ["directory", "filename"],
        "additionalProperties": False,
    }

    def run(self, directory: str, filename: str, content: str = "") -> str:
        if not (filename or "").strip():
            return "创建失败：filename 不能为空。"
        if os.sep in filename or (os.altsep and os.altsep in filename):
            return f"创建失败：filename 只能是文件名，不能包含路径分隔符（收到「{filename}」）。"

        folder = _safe_resolve(directory or ".")
        if isinstance(folder, str):
            return folder
        if not folder.exists():
            return f"创建失败：目录不存在 {folder}（可先用 createDir 创建）"
        if not folder.is_dir():
            return f"创建失败：{folder} 不是目录"

        target = folder / filename
        if target.exists():
            return f"创建失败：文件已存在 {target}（如需修改请用 editFile）"

        try:
            target.write_text(content, encoding="utf-8")
        except OSError as exc:
            return f"创建失败：{exc}"

        return (
            f"已创建文件：{target}\n"
            f"写入：{len(content)} 字符，{_human_size(len(content.encode('utf-8')))}（UTF-8）"
        )


class EditFileTool(Tool):
    name = "editFile"
    description = (
        "编辑已存在的纯文本文件。mode=overwrite 整体覆盖（会丢失原内容，"
        "需显式传 confirm=true）；mode=append 追加到末尾。"
        "不支持二进制文件；文件不存在时报错（请用 createFile）。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "文件路径"},
            "content": {"type": "string", "description": "要写入的内容"},
            "mode": {
                "type": "string",
                "enum": ["overwrite", "append"],
                "description": "overwrite 覆盖整体，append 追加末尾，默认 overwrite",
            },
            "confirm": {
                "type": "boolean",
                "description": (
                    "覆盖已有内容时必须显式置为 true，表示已知晓原内容会被丢弃。"
                    "append 模式无需该参数。"
                ),
            },
        },
        "required": ["path", "content"],
        "additionalProperties": False,
    }

    def run(
        self, path: str, content: str, mode: str = "overwrite", confirm: bool = False
    ) -> str:
        if not (path or "").strip():
            return "编辑失败：path 不能为空。"
        if mode not in ("overwrite", "append"):
            return f"编辑失败：mode 只能是 overwrite 或 append，收到「{mode}」。"

        target = _safe_resolve(path)
        if isinstance(target, str):
            return target
        if not target.exists():
            return f"编辑失败：文件不存在 {target}（如需新建请用 createFile）"
        if target.is_dir():
            return f"编辑失败：这是目录 {target}"

        if _is_binary(target):
            return f"编辑失败：{target.name} 是二进制文件，editFile 只支持纯文本。"

        # 覆盖写入是破坏性操作：原内容会整体丢失，必须显式确认
        if (
            mode == "overwrite"
            and target.exists()
            and target.stat().st_size > 0
            and _REQUIRE_CONFIRM.get()
            and not confirm
        ):
            return (
                f"拒绝覆盖：{target} 已有内容（{_human_size(target.stat().st_size)}），"
                "overwrite 会整体丢弃原内容。\n"
                "若确认要覆盖，请在调用时传 confirm=true；"
                "若只想追加，请用 mode=append。"
            )

        try:
            if mode == "append":
                with target.open("a", encoding="utf-8") as fh:
                    fh.write(content)
            else:
                target.write_text(content, encoding="utf-8")
            size = target.stat().st_size
        except OSError as exc:
            return f"编辑失败：{exc}"

        action = "追加" if mode == "append" else "覆盖"
        return (
            f"已{action}文件：{target}\n"
            f"本次写入：{len(content)} 字符；文件现有：{_human_size(size)}"
        )


class CreateDirTool(Tool):
    name = "createDir"
    description = "创建目录，自动创建缺失的上级目录。目录已存在时不会报错。"
    parameters = {
        "type": "object",
        "properties": {"path": {"type": "string", "description": "要创建的目录路径"}},
        "required": ["path"],
        "additionalProperties": False,
    }

    def run(self, path: str) -> str:
        if not (path or "").strip():
            return "创建目录失败：path 不能为空。"
        target = _safe_resolve(path)
        if isinstance(target, str):
            return target
        if target.exists():
            if target.is_dir():
                return f"目录已存在，无需创建：{target}"
            return f"创建目录失败：同名文件已存在 {target}"
        try:
            target.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return f"创建目录失败：{exc}"
        return f"已创建目录：{target}"


class RenamePathTool(Tool):
    """重命名或移动文件 / 目录。

    同一目录内改名即「重命名」，跨目录即「移动」，二者用同一个工具实现。
    """

    name = "renamePath"
    description = (
        "重命名或移动文件 / 目录。同目录改名即重命名，跨目录即移动。"
        "目标已存在时报错，不会覆盖；如确需覆盖请先删除目标。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "source": {"type": "string", "description": "源路径（文件或目录）"},
            "target": {"type": "string", "description": "目标路径（新名字或新位置）"},
            "overwrite": {
                "type": "boolean",
                "description": "目标已存在时是否覆盖，默认 false",
            },
        },
        "required": ["source", "target"],
        "additionalProperties": False,
    }

    def run(self, source: str, target: str, overwrite: bool = False) -> str:
        src = _safe_resolve(source)
        if isinstance(src, str):
            return src

        dst = _safe_resolve(target)
        if isinstance(dst, str):
            return dst

        if not src.exists():
            return f"重命名失败：源路径不存在 {src}"
        if src == dst:
            return "重命名失败：源路径与目标路径相同"
        if dst.exists():
            if not overwrite:
                return f"重命名失败：目标已存在 {dst}（如确需覆盖请传 overwrite=true）"
            # 目标存在且要求覆盖：额外确认
            if _REQUIRE_CONFIRM.get() and dst.is_dir():
                return f"重命名失败：目标目录已存在 {dst}，不允许目录覆盖，请先删除"

        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return f"重命名失败：无法创建目标父目录（{exc}）"

        kind = "目录" if src.is_dir() else "文件"
        try:
            if dst.exists() and overwrite:
                if dst.is_file():
                    dst.unlink()
            src.rename(dst)
        except OSError as exc:
            return f"重命名失败：{exc}"

        same_dir = src.parent == dst.parent
        action = "重命名" if same_dir else "移动"
        return f"已{action}{kind}：{src.name} → {dst}"


class DeleteDirTool(Tool):
    name = "deleteDir"
    description = (
        "删除目录，支持非空目录（连同其中所有内容一并删除，不可恢复）。"
        "拒绝删除文件系统根目录、当前工作目录及其上级目录。"
    )
    parameters = {
        "type": "object",
        "properties": {"path": {"type": "string", "description": "要删除的目录路径"}},
        "required": ["path"],
        "additionalProperties": False,
    }

    def run(self, path: str) -> str:
        if not (path or "").strip():
            return "删除目录失败：path 不能为空。"
        target = _safe_resolve(path)
        if isinstance(target, str):
            return target
        if not target.exists():
            return f"删除目录失败：路径不存在 {target}"
        if not target.is_dir():
            return f"删除目录失败：这不是目录 {target}（删除文件请用 deleteFile）"

        guard = _guard_destructive(target)
        if guard:
            return f"删除目录失败：{guard}"

        try:
            files = sum(1 for p in target.rglob("*") if p.is_file())
            subdirs = sum(1 for p in target.rglob("*") if p.is_dir())
            shutil.rmtree(target)
        except OSError as exc:
            return f"删除目录失败：{exc}"
        return f"已删除目录：{target}（其中 {files} 个文件、{subdirs} 个子目录）"


class DeleteFileTool(Tool):
    name = "deleteFile"
    description = "删除指定文件（不可恢复）。目录请用 deleteDir。"
    parameters = {
        "type": "object",
        "properties": {"path": {"type": "string", "description": "要删除的文件路径"}},
        "required": ["path"],
        "additionalProperties": False,
    }

    def run(self, path: str) -> str:
        if not (path or "").strip():
            return "删除文件失败：path 不能为空。"
        target = _safe_resolve(path)
        if isinstance(target, str):
            return target
        if not target.exists():
            return f"删除文件失败：文件不存在 {target}"
        if target.is_dir():
            return f"删除文件失败：这是目录 {target}（请用 deleteDir）"

        guard = _guard_destructive(target)
        if guard:
            return f"删除文件失败：{guard}"

        try:
            size = target.stat().st_size
            target.unlink()
        except OSError as exc:
            return f"删除文件失败：{exc}"
        return f"已删除文件：{target}（{_human_size(size)}）"


# 便捷：按默认配置构造全部工具
def build_fs_tools(settings: FsSettings | None = None) -> list[Tool]:
    """按配置构造全部文件系统工具。

    沙箱策略：
    - `allowed_roots` 为空 → 不限制（保持向后兼容，也便于单测）
    - `allowed_roots` 非空 → 只允许这些目录，并按 include_cwd 决定是否加入 cwd

    同时把确认策略写入上下文变量，供 editFile 等工具使用。
    """
    s = settings or FsSettings()

    explicit = _parse_roots(s.root_list)
    if explicit:
        roots = list(explicit)
        if s.include_cwd:
            try:
                cwd = Path.cwd().resolve()
                if cwd not in roots:
                    roots.append(cwd)
            except OSError:
                pass
        _ALLOWED_ROOTS.set(roots)
    else:
        # 未显式配置根目录：不做路径限制
        _ALLOWED_ROOTS.set([])

    _REQUIRE_CONFIRM.set(bool(s.require_confirm))

    return [
        GetCwdTool(),
        ListDirTool(s),
        GetFileTypeTool(),
        ReadFileTool(s),
        CreateFileTool(),
        EditFileTool(),
        CreateDirTool(),
        RenamePathTool(),
        DeleteDirTool(),
        DeleteFileTool(),
    ]


def get_allowed_roots() -> list[Path]:
    """当前生效的允许根目录（供测试与诊断）。"""
    return list(_ALLOWED_ROOTS.get())


__all__ = [
    "GetCwdTool",
    "ListDirTool",
    "GetFileTypeTool",
    "ReadFileTool",
    "CreateFileTool",
    "EditFileTool",
    "CreateDirTool",
    "RenamePathTool",
    "DeleteDirTool",
    "DeleteFileTool",
    "SandboxError",
    "build_fs_tools",
    "get_allowed_roots",
    "reset_sandbox",
]
