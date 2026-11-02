"""loadSkill 的 filename 解析测试。

覆盖需求要求的全部解析方式：
技能相对路径 / 项目相对路径 / 绝对路径 / 只给文件名递归搜索 /
多候选返回 / 目录提示 / 越界拒绝。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from core.skills import SkillRegistry, resolve_skill_file  # noqa: E402
from core.skills.loader import SkillError  # noqa: E402
from core.tools.skill import LoadSkillTool  # noqa: E402


@pytest.fixture
def project(tmp_path):
    """构造一个有 references/ scripts/ 的技能目录。"""
    skill_dir = tmp_path / ".agents" / "skills" / "demo"
    (skill_dir / "references").mkdir(parents=True)
    (skill_dir / "scripts").mkdir()
    (skill_dir / "SKILL.md").write_text(
        "---\nname: demo\ndescription: 演示\n---\n\nSKILL BODY\n", encoding="utf-8"
    )
    (skill_dir / "references" / "guide.md").write_text("GUIDE", encoding="utf-8")
    (skill_dir / "references" / "dup.md").write_text("DUP-A", encoding="utf-8")
    (skill_dir / "scripts" / "dup.md").write_text("DUP-B", encoding="utf-8")
    return tmp_path


@pytest.fixture
def setup(project):
    reg = SkillRegistry.discover(project)
    return reg, LoadSkillTool(reg), reg.get("demo")


# ---------------------------------------------------------------- 只给 name
def test_name_only_reads_skill_md(setup):
    _, tool, _ = setup
    out = tool.run("demo")
    assert "SKILL BODY" in out
    assert "完整说明" in out


def test_filename_does_not_reload_skill_md(setup):
    """给 filename 时不应把 SKILL.md 一起返回。"""
    _, tool, _ = setup
    out = tool.run("demo", "references/guide.md")
    assert "GUIDE" in out
    assert "SKILL BODY" not in out


# ---------------------------------------------------------------- 四种路径
def test_skill_relative_path(setup):
    _, tool, _ = setup
    assert "GUIDE" in tool.run("demo", "references/guide.md")


def test_project_relative_path(setup):
    _, tool, _ = setup
    out = tool.run("demo", ".agents/skills/demo/references/guide.md")
    assert "GUIDE" in out


def test_absolute_path(setup, project):
    _, tool, _ = setup
    absolute = project / ".agents" / "skills" / "demo" / "references" / "guide.md"
    assert "GUIDE" in tool.run("demo", str(absolute))


def test_bare_filename_recursive_search(setup):
    """只给文件名时递归查找，唯一命中就读取。"""
    _, tool, _ = setup
    out = tool.run("demo", "guide.md")
    assert "GUIDE" in out
    assert "references/guide.md" in out          # 返回相对路径便于模型理解


def test_forward_and_back_slash_both_work(setup):
    _, tool, _ = setup
    assert "GUIDE" in tool.run("demo", r"references\guide.md")


# ---------------------------------------------------------------- 多候选
def test_multiple_matches_return_candidates(setup):
    _, tool, _ = setup
    out = tool.run("demo", "dup.md")
    assert "多个" in out
    assert "references/dup.md" in out
    assert "scripts/dup.md" in out
    # 不应擅自读取其中一个
    assert "DUP-A" not in out and "DUP-B" not in out


def test_resolution_reports_ambiguity(setup, project):
    _, _, skill = setup
    res = resolve_skill_file(skill, "dup.md", project)
    assert res.is_ambiguous
    assert len(res.candidates) == 2


def test_exact_path_wins_over_search(setup, project):
    """精确路径命中时不走模糊搜索。"""
    _, _, skill = setup
    res = resolve_skill_file(skill, "scripts/dup.md", project)
    assert res.is_unique
    assert res.path.name == "dup.md"
    assert res.path.parent.name == "scripts"


# ---------------------------------------------------------------- 目录与缺失
def test_directory_lists_contents(setup):
    _, tool, _ = setup
    out = tool.run("demo", "references")
    assert "是一个目录" in out
    assert "guide.md" in out


def test_missing_file_message(setup):
    _, tool, _ = setup
    out = tool.run("demo", "nope.md")
    assert "找不到文件" in out


# ---------------------------------------------------------------- 沙箱
@pytest.mark.parametrize(
    "bad",
    ["../secret.txt", "../../../secret.txt", "../../other.md"],
)
def test_traversal_rejected(setup, bad):
    _, tool, _ = setup
    assert "拒绝访问" in tool.run("demo", bad)


def test_absolute_outside_rejected(setup, project):
    _, tool, _ = setup
    outside = project / "secret.txt"
    outside.write_text("SECRET", encoding="utf-8")
    out = tool.run("demo", str(outside))
    assert "拒绝访问" in out
    assert "SECRET" not in out


def test_sibling_skill_not_accessible(setup, project):
    """不能读到同项目下其他技能的文件。"""
    other = project / ".agents" / "skills" / "other"
    other.mkdir(parents=True)
    (other / "SKILL.md").write_text(
        "---\nname: other\ndescription: 另一个\n---\n\nOTHER\n", encoding="utf-8"
    )
    (other / "secret.md").write_text("OTHER SECRET", encoding="utf-8")

    reg = SkillRegistry.discover(project)
    tool = LoadSkillTool(reg)
    out = tool.run("demo", "../other/secret.md")
    assert "拒绝访问" in out
    assert "OTHER SECRET" not in out


# ---------------------------------------------------------------- 其它
def test_project_root_optional(setup):
    """不给 project_root 时，前三种解析仍可用。"""
    _, _, skill = setup
    res = resolve_skill_file(skill, "references/guide.md")
    assert res.is_unique


def test_empty_filename_treated_as_no_filename(setup):
    _, tool, _ = setup
    out = tool.run("demo", "   ")
    assert "SKILL BODY" in out


def test_skill_md_can_be_loaded_explicitly(setup):
    _, tool, _ = setup
    out = tool.run("demo", "SKILL.md")
    assert "SKILL BODY" in out


def test_resolve_empty_filename_raises(setup):
    _, _, skill = setup
    with pytest.raises(SkillError):
        resolve_skill_file(skill, "   ")
