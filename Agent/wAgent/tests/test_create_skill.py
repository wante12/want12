"""createSkill 工具测试。

覆盖：名称规范化与校验、SKILL.md 生成格式、拒绝覆盖、
以及「辅助文件交给 fileops 工具」的协同。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from core.skills import SkillRegistry  # noqa: E402
from core.tools.base import ToolRegistry  # noqa: E402
from core.tools.create_skill import (  # noqa: E402
    CreateSkillTool,
    build_create_skill_tool,
    normalize_name,
    render_skill_md,
    split_context,
    validate_name,
)

CONTEXT = "撰写 Markdown 文档\n\n## 步骤\n1. 确认主题\n2. 写正文"


@pytest.fixture
def tool(tmp_path):
    return CreateSkillTool(project_root=tmp_path)


# ---------------------------------------------------------------- 名称规范化
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("pdf", "pdf"),
        ("PDF", "pdf"),
        ("pdf-summary", "pdf-summary"),
        ("PDF Summary", "pdf-summary"),
        ("doc_writer", "doc-writer"),
        ("My  Tool", "my-tool"),
        ("a--b", "a-b"),
        ("--x--", "x"),
        ("tool2024", "tool2024"),
    ],
)
def test_normalize_name(raw, expected):
    name, _ = normalize_name(raw)
    assert name == expected


def test_normalize_reports_changes():
    _, notes = normalize_name("PDF Summary")
    assert "转为小写" in notes


@pytest.mark.parametrize("bad", ["", "a" * 65, "-abc", "abc-", "a--b"])
def test_validate_name_rejects(bad):
    assert validate_name(bad) is not None


@pytest.mark.parametrize("ok", ["pdf", "pdf-summary", "a", "x1-y2", "a" * 64])
def test_validate_name_accepts(ok):
    assert validate_name(ok) is None


# ---------------------------------------------------------------- 创建
def test_creates_skill_dir_and_file(tool, tmp_path):
    out = tool.run("doc-writer", CONTEXT)
    assert "已创建技能" in out

    skill_dir = tmp_path / ".agents" / "skills" / "doc-writer"
    assert skill_dir.is_dir()
    assert (skill_dir / "SKILL.md").is_file()


def test_generated_frontmatter_is_valid(tool, tmp_path):
    tool.run("doc-writer", CONTEXT)
    skill_file = tmp_path / ".agents" / "skills" / "doc-writer" / "SKILL.md"
    text = skill_file.read_text(encoding="utf-8")

    assert text.startswith("---\n")
    assert "name: doc-writer" in text
    assert "description: '撰写 Markdown 文档'" in text
    assert "## 步骤" in text


def test_generated_skill_is_discoverable(tool, tmp_path):
    """生成的技能能被 SkillRegistry 正常发现。"""
    tool.run("doc-writer", CONTEXT)
    registry = SkillRegistry.discover(tmp_path)

    assert "doc-writer" in registry
    skill = registry.get("doc-writer")
    assert skill.description == "撰写 Markdown 文档"
    assert "## 步骤" in skill.skill_file.read_text(encoding="utf-8")


def test_directory_name_equals_frontmatter_name(tool, tmp_path):
    tool.run("PDF Summary", CONTEXT)
    d = tmp_path / ".agents" / "skills" / "pdf-summary"
    assert d.is_dir()
    assert "name: pdf-summary" in (d / "SKILL.md").read_text(encoding="utf-8")


def test_creates_skills_dir_when_absent(tool, tmp_path):
    assert not (tmp_path / ".agents").exists()
    tool.run("first-one", CONTEXT)
    assert (tmp_path / ".agents" / "skills" / "first-one").is_dir()


def test_description_with_single_quote_is_escaped(tool, tmp_path):
    tool.run("quoted", "It's a test\n\n正文")
    text = (tmp_path / ".agents" / "skills" / "quoted" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    assert "description: 'It''s a test'" in text
    # 解析回来应与原文一致
    assert SkillRegistry.discover(tmp_path).get("quoted").description == "It's a test"


def test_accepts_context_with_existing_frontmatter(tool, tmp_path):
    context = "---\nname: whatever\ndescription: 从 frontmatter 取描述\n---\n\n正文内容"
    tool.run("with-fm", context)
    skill = SkillRegistry.discover(tmp_path).get("with-fm")
    assert skill.description == "从 frontmatter 取描述"
    assert "正文内容" in skill.skill_file.read_text(encoding="utf-8")


# ---------------------------------------------------------------- 拒绝覆盖
def test_refuses_to_overwrite(tool, tmp_path):
    tool.run("dup", CONTEXT)
    target = tmp_path / ".agents" / "skills" / "dup" / "SKILL.md"
    original = target.read_text(encoding="utf-8")

    out = tool.run("dup", "新的描述\n新正文")
    assert "已存在" in out
    assert "避免覆盖" in out
    assert target.read_text(encoding="utf-8") == original     # 内容未变


def test_refuses_when_normalized_name_collides(tool, tmp_path):
    tool.run("pdf-summary", CONTEXT)
    out = tool.run("PDF Summary", CONTEXT)      # 规范化后同名
    assert "已存在" in out


# ---------------------------------------------------------------- 参数校验
@pytest.mark.parametrize("name", ["PDF摘要", "笔记工具", "文档"])
def test_rejects_non_ascii_name(tool, name):
    out = tool.run(name, CONTEXT)
    assert "非英文字符" in out


def test_rejects_empty_name(tool):
    assert "name 不能为空" in tool.run("  ", CONTEXT)


def test_rejects_too_long_name(tool):
    assert "过长" in tool.run("a" * 70, CONTEXT)


def test_rejects_empty_context(tool):
    assert "skillContext 不能为空" in tool.run("x-skill", "   ")


def test_rejects_context_without_body(tool):
    out = tool.run("only-desc", "只有一行描述")
    assert "缺少正文" in out


def test_rejects_angle_brackets_in_description(tool):
    out = tool.run("angle", "用 <tag> 做标记\n\n正文")
    assert "尖括号" in out


# ---------------------------------------------------------------- 渲染与拆分
def test_render_skill_md_shape():
    text = render_skill_md("demo", "描述", "正文")
    assert text.startswith("---\nname: demo\n")
    assert text.endswith("正文\n")


def test_split_context_first_line_is_description():
    desc, body = split_context("描述行\n\n正文第一段\n正文第二段")
    assert desc == "描述行"
    assert "正文第一段" in body


# ---------------------------------------------------------------- 协同
def test_aux_dirs_created_by_fileops_tools(tool, tmp_path):
    """references/ 等辅助目录由 createDir / createFile 完成。"""
    from core.tools.filesystem import CreateDirTool, CreateFileTool

    tool.run("with-refs", CONTEXT)
    skill_dir = tmp_path / ".agents" / "skills" / "with-refs"

    out_dir = CreateDirTool().run(str(skill_dir / "references"))
    assert "已创建目录" in out_dir
    out_file = CreateFileTool().run(str(skill_dir / "references"), "guide.md", "# 指南")
    assert "已创建文件" in out_file

    assert (skill_dir / "references" / "guide.md").is_file()


def test_never_raises_through_registry(tool, tmp_path):
    reg = ToolRegistry()
    reg.register(tool)
    for payload in ['{"name": 1, "skillContext": "x"}', "{}", '{"name":"a"}']:
        out = reg.execute("createSkill", payload)
        assert isinstance(out, str) and out
        assert "Traceback" not in out


def test_builder_uses_registry_root(tmp_path):
    registry = SkillRegistry.discover(tmp_path)
    built = build_create_skill_tool(registry)
    built.run("from-registry", CONTEXT)
    assert (tmp_path / ".agents" / "skills" / "from-registry" / "SKILL.md").is_file()


def test_registered_even_without_existing_skills(tmp_path):
    from core.app import build_registry

    empty = SkillRegistry.discover(tmp_path)
    registry = build_registry(skills=empty)
    assert "createSkill" in registry.names
    assert "loadSkill" not in registry.names      # 没有技能时仍不注册 loadSkill


# ---------------------------------------------------------------- 当次会话可用
def test_new_skill_loadable_in_same_session(tmp_path):
    """创建后立即注册到当前会话，loadSkill 无需重启即可用。"""
    from core.app import build_registry

    registry = SkillRegistry.discover(tmp_path)
    tools = build_registry(skills=registry)
    assert "loadSkill" not in tools.names        # 起初没有技能

    out = tools.execute(
        "createSkill", '{"name":"live-skill","skillContext":"描述行\\n\\n正文内容"}'
    )
    assert "已创建技能" in out

    # loadSkill 被动态补注册
    assert "loadSkill" in tools.names
    loaded = tools.execute("loadSkill", '{"name":"live-skill"}')
    assert "正文内容" in loaded


def test_new_skill_registered_in_existing_registry(tmp_path):
    """已有技能时，新技能同样进入注册表，不重启即可加载。"""
    seed = tmp_path / ".agents" / "skills" / "seed"
    seed.mkdir(parents=True)
    (seed / "SKILL.md").write_text(
        "---\nname: seed\ndescription: 已有技能\n---\n\nSEED\n", encoding="utf-8"
    )
    registry = SkillRegistry.discover(tmp_path)
    tool = CreateSkillTool(registry=registry, project_root=tmp_path)

    tool.run("another-one", "描述\n正文")
    assert "another-one" in registry
    assert registry.get("another-one").description == "描述"
