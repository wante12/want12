"""扣分项修复的回归测试。

覆盖：
- stdio 配置解析与推断
- 闰年工具进入工具集
- renamePath 重命名 / 移动
- 路径白名单（沙箱）
- 覆盖写入确认
- AGENT.md 单数兼容
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from core import build_agent  # noqa: E402
from core.config import AppConfig, FsSettings  # noqa: E402
from core.session import find_agents_md, load_agents_md  # noqa: E402
from core.tools.builtin import IsLeapYearTool  # noqa: E402
from core.tools.filesystem import (  # noqa: E402
    EditFileTool,
    RenamePathTool,
    build_fs_tools,
    get_allowed_roots,
    reset_sandbox,
)


# ================================================================== 闰年工具
def test_leap_year_tool_basic():
    t = IsLeapYearTool()
    assert "是闰年" in t.run(2024)
    assert "不是闰年" in t.run(2023)


def test_leap_year_tool_rules():
    """世纪年规则：整百需被 400 整除。"""
    t = IsLeapYearTool()
    assert "不是闰年" in t.run(1900)
    assert "是闰年" in t.run(2000)
    assert "是闰年" in t.run(1600)


def test_leap_year_tool_rejects_non_positive():
    t = IsLeapYearTool()
    assert "必须大于 0" in t.run(0)
    assert "必须大于 0" in t.run(-5)


def test_leap_year_in_agent_toolset():
    """闰年工具必须出现在 Agent 的工具集里（此前只在 Practice02）。"""
    agent = build_agent()
    assert "isLeapYear" in agent.tool_names


def test_leap_year_tool_schema():
    t = IsLeapYearTool()
    schema = t.to_schema()
    fn = schema["function"]
    assert fn["name"] == "isLeapYear"
    assert "year" in fn["parameters"]["properties"]
    assert fn["parameters"]["required"] == ["year"]


# ================================================================== renamePath
def test_rename_same_dir(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("x", encoding="utf-8")
    out = RenamePathTool().run(str(f), str(tmp_path / "b.txt"))
    assert "已重命名" in out
    assert not f.exists()
    assert (tmp_path / "b.txt").exists()


def test_rename_move_across_dirs(tmp_path):
    src = tmp_path / "a.txt"
    src.write_text("x", encoding="utf-8")
    sub = tmp_path / "sub"
    sub.mkdir()
    out = RenamePathTool().run(str(src), str(sub / "a.txt"))
    assert "已移动" in out
    assert (sub / "a.txt").exists()


def test_rename_directory(tmp_path):
    d = tmp_path / "old"
    d.mkdir()
    out = RenamePathTool().run(str(d), str(tmp_path / "new"))
    assert "目录" in out
    assert (tmp_path / "new").is_dir()


def test_rename_missing_source(tmp_path):
    out = RenamePathTool().run(str(tmp_path / "no.txt"), str(tmp_path / "x.txt"))
    assert "源路径不存在" in out


def test_rename_refuses_existing_target(tmp_path):
    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    a.write_text("A", encoding="utf-8")
    b.write_text("B", encoding="utf-8")
    out = RenamePathTool().run(str(a), str(b))
    assert "目标已存在" in out
    assert b.read_text(encoding="utf-8") == "B"


def test_rename_with_overwrite(tmp_path):
    a = tmp_path / "a.txt"
    b = tmp_path / "b.txt"
    a.write_text("A", encoding="utf-8")
    b.write_text("B", encoding="utf-8")
    out = RenamePathTool().run(str(a), str(b), overwrite=True)
    assert "已重命名" in out
    assert b.read_text(encoding="utf-8") == "A"


def test_rename_same_path(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("x", encoding="utf-8")
    out = RenamePathTool().run(str(f), str(f))
    assert "相同" in out


def test_rename_in_toolset():
    names = {t.name for t in build_fs_tools()}
    assert "renamePath" in names


# ================================================================== 沙箱
def test_no_sandbox_when_roots_empty(tmp_path):
    """未配置 allowed_roots 时不限制路径（向后兼容）。"""
    reset_sandbox()
    build_fs_tools(FsSettings(allowed_roots=""))
    assert get_allowed_roots() == []


def test_sandbox_allows_inside(tmp_path):
    build_fs_tools(FsSettings(allowed_roots=str(tmp_path), include_cwd=False))
    roots = get_allowed_roots()
    assert str(tmp_path) in [str(r) for r in roots]

    from core.tools.filesystem import CreateFileTool

    out = CreateFileTool().run(str(tmp_path), "ok.txt", "hello")
    assert "已创建文件" in out


def test_sandbox_blocks_outside(tmp_path):
    inside = tmp_path / "inside"
    outside = tmp_path / "outside"
    inside.mkdir()
    outside.mkdir()

    build_fs_tools(FsSettings(allowed_roots=str(inside), include_cwd=False))
    from core.tools.filesystem import CreateFileTool

    out = CreateFileTool().run(str(outside), "x.txt", "hello")
    assert "拒绝访问" in out
    assert not (outside / "x.txt").exists()


def test_sandbox_blocks_read_outside(tmp_path):
    inside = tmp_path / "in"
    inside.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("s", encoding="utf-8")

    build_fs_tools(FsSettings(allowed_roots=str(inside), include_cwd=False))
    from core.tools.filesystem import ReadFileTool

    out = ReadFileTool().run(str(secret))
    assert "拒绝访问" in out


def test_sandbox_includes_cwd_by_default(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    build_fs_tools(FsSettings(allowed_roots=str(tmp_path), include_cwd=True))
    roots = [str(r) for r in get_allowed_roots()]
    assert str(tmp_path.resolve()) in roots


def test_fs_settings_root_list_parsing():
    s = FsSettings(allowed_roots="D:/a, D:/b; D:/c")
    assert s.root_list == ["D:/a", "D:/b", "D:/c"]


# ================================================================== 覆盖确认
def test_editfile_refuses_overwrite_without_confirm(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("old", encoding="utf-8")
    out = EditFileTool().run(str(f), "new", "overwrite")
    assert "拒绝覆盖" in out
    assert f.read_text(encoding="utf-8") == "old"


def test_editfile_overwrite_with_confirm(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("old", encoding="utf-8")
    out = EditFileTool().run(str(f), "new", "overwrite", confirm=True)
    assert "已覆盖文件" in out


def test_editfile_append_needs_no_confirm(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("A", encoding="utf-8")
    out = EditFileTool().run(str(f), "B", "append")
    assert "已追加文件" in out


def test_editfile_empty_file_can_overwrite(tmp_path):
    """空文件覆盖不丢内容，无需确认。"""
    f = tmp_path / "a.txt"
    f.write_text("", encoding="utf-8")
    out = EditFileTool().run(str(f), "new", "overwrite")
    assert "已覆盖文件" in out


def test_confirm_can_be_disabled(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("old", encoding="utf-8")
    build_fs_tools(FsSettings(require_confirm=False))
    out = EditFileTool().run(str(f), "new", "overwrite")
    assert "已覆盖文件" in out


# ================================================================== AGENT.md
def test_agent_md_singular_supported(tmp_path):
    (tmp_path / "AGENT.md").write_text("# 单数", encoding="utf-8")
    found = find_agents_md(tmp_path)
    assert found is not None
    assert found.name == "AGENT.md"


def test_agents_md_plural_preferred(tmp_path):
    (tmp_path / "AGENT.md").write_text("# 单数", encoding="utf-8")
    (tmp_path / "AGENTS.md").write_text("# 复数", encoding="utf-8")
    found = find_agents_md(tmp_path)
    assert found.name == "AGENTS.md"


def test_agent_md_content_loaded(tmp_path):
    (tmp_path / "AGENT.md").write_text("# 约定\n- 用中文", encoding="utf-8")
    loaded = load_agents_md(tmp_path)
    assert loaded is not None
    assert "用中文" in loaded.content


def test_no_agents_md(tmp_path):
    assert find_agents_md(tmp_path) is None


def test_custom_filename_only(tmp_path):
    """配置里指定自定义文件名时，只查该名字。"""
    (tmp_path / "AGENTS.md").write_text("x", encoding="utf-8")
    assert find_agents_md(tmp_path, filename="CUSTOM.md") is None


# ================================================================== 配置模板
def test_config_example_exists():
    """仓库必须包含配置模板，供他人克隆后参考。"""
    path = BASE / "config.example.ini"
    assert path.is_file()


def test_config_example_has_no_real_key():
    text = (BASE / "config.example.ini").read_text(encoding="utf-8")
    assert "sk-请替换" in text
    # 不能出现真实长度的密钥
    import re

    assert not re.search(r"sk-[a-f0-9]{20,}", text)


def test_config_example_loads(tmp_path):
    src = BASE / "config.example.ini"
    dst = tmp_path / "config.ini"
    dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    cfg = AppConfig.load(dst)
    assert cfg.llm.model
    assert cfg.fs.require_confirm is True


def test_config_example_documents_sandbox():
    text = (BASE / "config.example.ini").read_text(encoding="utf-8")
    assert "allowed_roots" in text
    assert "require_confirm" in text
