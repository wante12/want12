"""文件系统工具测试。

全部在 pytest 的 tmp_path 中进行，不触碰真实项目文件。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from core.config import FsSettings  # noqa: E402
from core.tools.base import ToolRegistry  # noqa: E402
from core.tools.filesystem import (  # noqa: E402
    CreateDirTool,
    CreateFileTool,
    DeleteDirTool,
    DeleteFileTool,
    EditFileTool,
    GetCwdTool,
    GetFileTypeTool,
    ListDirTool,
    ReadFileTool,
    build_fs_tools,
)


# ---------------------------------------------------------------- 1. getCwd
def test_getcwd_returns_cwd():
    out = GetCwdTool().run()
    assert "当前工作目录" in out
    assert str(Path.cwd()) in out


# ---------------------------------------------------------------- 2. listDir
def test_listdir_lists_files_and_dirs(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "a.txt").write_text("hi", encoding="utf-8")

    out = ListDirTool().run(str(tmp_path))
    assert "a.txt" in out
    assert "sub/" in out
    assert "共 2 项" in out
    assert "[目录]" in out and "[文件]" in out


def test_listdir_recursive(tmp_path):
    nested = tmp_path / "x" / "y"
    nested.mkdir(parents=True)
    (nested / "deep.txt").write_text("d", encoding="utf-8")

    out = ListDirTool().run(str(tmp_path), True)
    assert "deep.txt" in out
    assert "x/y/" in out          # 分隔符统一为 /


def test_listdir_missing_path(tmp_path):
    out = ListDirTool().run(str(tmp_path / "nope"))
    assert "路径不存在" in out


def test_listdir_on_file(tmp_path):
    f = tmp_path / "f.txt"
    f.write_text("x", encoding="utf-8")
    assert "不是目录" in ListDirTool().run(str(f))


def test_listdir_respects_limit(tmp_path):
    for i in range(5):
        (tmp_path / f"f{i}.txt").write_text("x", encoding="utf-8")
    out = ListDirTool(FsSettings(max_list_entries=2)).run(str(tmp_path))
    assert "仅显示前 2 项" in out


def test_listdir_empty(tmp_path):
    assert "空目录" in ListDirTool().run(str(tmp_path))


# ---------------------------------------------------------------- 3. getFileType
def test_filetype_text(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("print(1)", encoding="utf-8")
    out = GetFileTypeTool().run(str(f))
    assert "扩展名：.py" in out
    assert "纯文本" in out
    assert "text/x-python" in out


def test_filetype_binary(tmp_path):
    f = tmp_path / "img.png"
    f.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR")
    out = GetFileTypeTool().run(str(f))
    assert "二进制" in out
    assert "不支持" in out


def test_filetype_directory(tmp_path):
    assert "这是目录" in GetFileTypeTool().run(str(tmp_path))


# ---------------------------------------------------------------- 4. readFile
def test_readfile_content(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("第一行\n第二行\n", encoding="utf-8")
    out = ReadFileTool().run(str(f))
    assert "第一行" in out and "第二行" in out
    assert "2 行" in out


def test_readfile_rejects_binary(tmp_path):
    f = tmp_path / "b.bin"
    f.write_bytes(b"\x00\x01\x02")
    out = ReadFileTool().run(str(f))
    assert "二进制文件" in out


def test_readfile_missing(tmp_path):
    assert "文件不存在" in ReadFileTool().run(str(tmp_path / "no.txt"))


def test_readfile_truncates(tmp_path):
    f = tmp_path / "big.txt"
    f.write_text("A" * 500, encoding="utf-8")
    out = ReadFileTool(FsSettings(max_read_chars=100)).run(str(f))
    assert "已截断" in out


def test_readfile_gbk_file(tmp_path):
    """GBK 编码的中文文件也应能正确读取。"""
    f = tmp_path / "gbk.txt"
    f.write_bytes("中文内容".encode("gbk"))
    out = ReadFileTool().run(str(f))
    assert "中文内容" in out
    assert "gbk" in out.lower()


# ---------------------------------------------------------------- 5. createFile
def test_createfile(tmp_path):
    out = CreateFileTool().run(str(tmp_path), "new.txt", "hello")
    assert "已创建文件" in out
    assert (tmp_path / "new.txt").read_text(encoding="utf-8") == "hello"


def test_createfile_default_empty(tmp_path):
    CreateFileTool().run(str(tmp_path), "empty.txt")
    assert (tmp_path / "empty.txt").read_text(encoding="utf-8") == ""


def test_createfile_refuses_overwrite(tmp_path):
    (tmp_path / "a.txt").write_text("old", encoding="utf-8")
    out = CreateFileTool().run(str(tmp_path), "a.txt", "new")
    assert "已存在" in out
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "old"


def test_createfile_missing_dir(tmp_path):
    out = CreateFileTool().run(str(tmp_path / "nope"), "a.txt")
    assert "目录不存在" in out


def test_createfile_rejects_path_in_filename(tmp_path):
    out = CreateFileTool().run(str(tmp_path), "sub/a.txt")
    assert "不能包含路径分隔符" in out


# ---------------------------------------------------------------- 6. editFile
def test_editfile_overwrite(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("old", encoding="utf-8")
    out = EditFileTool().run(str(f), "new", "overwrite")
    assert "已覆盖文件" in out
    assert f.read_text(encoding="utf-8") == "new"


def test_editfile_append(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("A", encoding="utf-8")
    out = EditFileTool().run(str(f), "B", "append")
    assert "已追加文件" in out
    assert f.read_text(encoding="utf-8") == "AB"


def test_editfile_rejects_binary(tmp_path):
    f = tmp_path / "b.bin"
    f.write_bytes(b"\x00\x01")
    assert "二进制文件" in EditFileTool().run(str(f), "x")


def test_editfile_bad_mode(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("x", encoding="utf-8")
    assert "只能是 overwrite 或 append" in EditFileTool().run(str(f), "y", "insert")


def test_editfile_missing(tmp_path):
    assert "文件不存在" in EditFileTool().run(str(tmp_path / "no.txt"), "x")


# ---------------------------------------------------------------- 7. createDir
def test_createdir_nested(tmp_path):
    target = tmp_path / "a" / "b" / "c"
    out = CreateDirTool().run(str(target))
    assert "已创建目录" in out
    assert target.is_dir()


def test_createdir_existing(tmp_path):
    assert "已存在" in CreateDirTool().run(str(tmp_path))


# ---------------------------------------------------------------- 8. deleteDir
def test_deletedir_non_empty(tmp_path):
    target = tmp_path / "victim"
    (target / "sub").mkdir(parents=True)
    (target / "sub" / "f.txt").write_text("x", encoding="utf-8")

    out = DeleteDirTool().run(str(target))
    assert "已删除目录" in out
    assert "1 个文件" in out      # f.txt
    assert "1 个子目录" in out     # sub
    assert not target.exists()


def test_deletedir_missing(tmp_path):
    assert "路径不存在" in DeleteDirTool().run(str(tmp_path / "nope"))


def test_deletedir_on_file(tmp_path):
    f = tmp_path / "f.txt"
    f.write_text("x", encoding="utf-8")
    assert "这不是目录" in DeleteDirTool().run(str(f))


def test_deletedir_guards_cwd():
    """不应允许删除当前工作目录。"""
    out = DeleteDirTool().run(str(Path.cwd()))
    assert "拒绝删除" in out
    assert Path.cwd().exists()


# ---------------------------------------------------------------- 9. deleteFile
def test_deletefile(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("x", encoding="utf-8")
    out = DeleteFileTool().run(str(f))
    assert "已删除文件" in out
    assert not f.exists()


def test_deletefile_on_dir(tmp_path):
    assert "请用 deleteDir" in DeleteFileTool().run(str(tmp_path))


def test_deletefile_missing(tmp_path):
    assert "文件不存在" in DeleteFileTool().run(str(tmp_path / "no.txt"))


# ---------------------------------------------------------------- 集成
def test_all_tools_registered():
    names = {t.name for t in build_fs_tools()}
    assert names == {
        "getCwd", "listDir", "getFileType", "readFile", "createFile",
        "editFile", "createDir", "deleteDir", "deleteFile",
    }


def test_tools_never_raise_through_registry(tmp_path):
    reg = ToolRegistry()
    for t in build_fs_tools():
        reg.register(t)
    # 故意传错参数，应返回可读的错误文本而非抛异常
    for tool_name, payload in [
        ("readFile", '{"path": 123}'),
        ("deleteDir", "{}"),
        ("createFile", '{"directory": ".", "filename": ""}'),
        ("editFile", '{"path": ".", "content": "x", "mode": "bad"}'),
    ]:
        out = reg.execute(tool_name, payload)
        assert isinstance(out, str) and out, tool_name
        assert "Traceback" not in out


def test_create_read_edit_delete_roundtrip(tmp_path):
    """完整链路：建目录 → 建文件 → 追加 → 读 → 删文件 → 删目录。"""
    d = tmp_path / "proj"
    assert "已创建目录" in CreateDirTool().run(str(d))

    f = d / "log.txt"
    assert "已创建文件" in CreateFileTool().run(str(d), "log.txt", "第一行\n")
    assert "已追加文件" in EditFileTool().run(str(f), "第二行\n", "append")

    content = ReadFileTool().run(str(f))
    assert "第一行" in content and "第二行" in content

    assert "已删除文件" in DeleteFileTool().run(str(f))
    assert "已删除目录" in DeleteDirTool().run(str(d))
    assert not d.exists()
