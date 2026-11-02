"""Agent Skills 发现与注册测试。

覆盖：frontmatter 解析、字段校验、目录扫描、重名与损坏容错、
以及「初始化只读 frontmatter、不读正文」这一关键约束。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from core.skills import (  # noqa: E402
    SkillError,
    SkillRegistry,
    discover_skills,
    load_skill,
    parse_frontmatter,
)
from core.skills.loader import read_frontmatter  # noqa: E402


# ---------------------------------------------------------------- 工具函数
def write_skill(root: Path, dirname: str, frontmatter: str, body: str = "正文内容") -> Path:
    """在 root/.agents/skills/dirname 下创建一个 SKILL.md。"""
    skill_dir = root / ".agents" / "skills" / dirname
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\n{frontmatter}\n---\n\n{body}\n", encoding="utf-8"
    )
    return skill_dir


# ---------------------------------------------------------------- frontmatter
def test_parse_simple_frontmatter():
    meta = parse_frontmatter("name: demo\ndescription: 示例技能")
    assert meta["name"] == "demo"
    assert meta["description"] == "示例技能"


def test_parse_block_scalar_description():
    meta = parse_frontmatter("name: d\ndescription: |\n  第一行\n  第二行")
    assert "第一行" in meta["description"]
    assert "第二行" in meta["description"]


def test_parse_keeps_extra_fields():
    meta = parse_frontmatter("name: d\ndescription: x\nversion: 1.0.0\nlayout: flat")
    assert meta["version"] == "1.0.0"
    assert meta["layout"] == "flat"


def test_parse_empty_raises():
    with pytest.raises(SkillError):
        parse_frontmatter("")


def test_parse_non_mapping_raises():
    with pytest.raises(SkillError):
        parse_frontmatter("- a\n- b")


# ---------------------------------------------------------------- 单目录加载
def test_load_skill_ok(tmp_path):
    d = write_skill(tmp_path, "demo", "name: demo\ndescription: 说明")
    skill = load_skill(d)
    assert skill.name == "demo"
    assert skill.description == "说明"
    assert skill.path == d
    assert skill.skill_file.name == "SKILL.md"


def test_load_skill_missing_file(tmp_path):
    d = tmp_path / "empty"
    d.mkdir()
    with pytest.raises(SkillError, match="缺少 SKILL.md"):
        load_skill(d)


def test_load_skill_missing_name(tmp_path):
    d = write_skill(tmp_path, "x", "description: 只有描述")
    with pytest.raises(SkillError, match="缺少必需字段 name"):
        load_skill(d)


def test_load_skill_missing_description(tmp_path):
    d = write_skill(tmp_path, "x", "name: only-name")
    with pytest.raises(SkillError, match="缺少必需字段 description"):
        load_skill(d)


def test_load_skill_blank_field(tmp_path):
    d = write_skill(tmp_path, "x", 'name: "   "\ndescription: ok')
    with pytest.raises(SkillError, match="不能为空"):
        load_skill(d)


def test_load_skill_non_string_field(tmp_path):
    d = write_skill(tmp_path, "x", "name: 123\ndescription: ok")
    with pytest.raises(SkillError, match="必须是字符串"):
        load_skill(d)


def test_no_frontmatter_fence(tmp_path):
    d = tmp_path / ".agents" / "skills" / "bad"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text("name: x\n", encoding="utf-8")
    with pytest.raises(SkillError, match="必须以 --- 开头"):
        load_skill(d)


def test_unclosed_frontmatter(tmp_path):
    d = tmp_path / ".agents" / "skills" / "bad2"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text("---\nname: x\ndescription: y\n", encoding="utf-8")
    with pytest.raises(SkillError, match="缺少结束分隔符"):
        load_skill(d)


# ---------------------------------------------------------------- 只读正文约束
def test_body_is_not_read(tmp_path):
    """正文里放非法内容也不该影响加载——证明正文根本没被解析。"""
    d = write_skill(
        tmp_path,
        "demo",
        "name: demo\ndescription: ok",
        body="{ 这不是合法 YAML: [ 也未闭合",
    )
    skill = load_skill(d)
    assert skill.name == "demo"


def test_read_frontmatter_stops_at_fence(tmp_path):
    """read_frontmatter 只返回 frontmatter，不包含正文。"""
    d = write_skill(tmp_path, "demo", "name: demo\ndescription: ok", body="不该出现的内容")
    meta = read_frontmatter(d / "SKILL.md")
    assert meta["name"] == "demo"
    assert "不该出现的内容" not in str(meta)


# ---------------------------------------------------------------- 目录扫描
def test_discover_multiple(tmp_path):
    write_skill(tmp_path, "a", "name: alpha\ndescription: 甲")
    write_skill(tmp_path, "b", "name: beta\ndescription: 乙")

    skills, errors = discover_skills(tmp_path)
    assert {s.name for s in skills} == {"alpha", "beta"}
    assert errors == []


def test_discover_name_differs_from_dirname(tmp_path):
    """name 取自 frontmatter，不是目录名。"""
    write_skill(tmp_path, "dir-name", "name: real-name\ndescription: x")
    skills, _ = discover_skills(tmp_path)
    assert skills[0].name == "real-name"
    assert skills[0].path.name == "dir-name"


def test_discover_missing_dir_returns_empty(tmp_path):
    skills, errors = discover_skills(tmp_path)
    assert skills == [] and errors == []


def test_discover_skips_bad_skill(tmp_path):
    write_skill(tmp_path, "good", "name: good\ndescription: ok")
    (tmp_path / ".agents" / "skills" / "broken").mkdir(parents=True)
    (tmp_path / ".agents" / "skills" / "broken" / "SKILL.md").write_text(
        "没有 frontmatter", encoding="utf-8"
    )

    skills, errors = discover_skills(tmp_path)
    assert [s.name for s in skills] == ["good"]      # 好的仍能加载
    assert len(errors) == 1                          # 坏的被记录


def test_discover_detects_duplicate_names(tmp_path):
    write_skill(tmp_path, "a", "name: same\ndescription: 一")
    write_skill(tmp_path, "b", "name: same\ndescription: 二")

    skills, errors = discover_skills(tmp_path)
    assert len(skills) == 1
    assert any("重复" in str(e) for e in errors)


# ---------------------------------------------------------------- 注册表
def test_registry_discover_and_query(tmp_path):
    write_skill(tmp_path, "a", "name: alpha\ndescription: 甲")
    reg = SkillRegistry.discover(tmp_path)

    assert len(reg) == 1
    assert "alpha" in reg
    assert reg.get("alpha") is not None
    assert reg.get("nope") is None
    assert reg.names == ["alpha"]
    assert reg.root == tmp_path


def test_registry_specs_are_flattened(tmp_path):
    write_skill(tmp_path, "a", "name: alpha\ndescription: |\n  第一行\n  第二行")
    reg = SkillRegistry.discover(tmp_path)
    spec = reg.specs()[0]
    assert spec["name"] == "alpha"
    assert "\n" not in spec["description"]      # 压平成单行


def test_registry_errors_exposed(tmp_path):
    (tmp_path / ".agents" / "skills" / "bad").mkdir(parents=True)
    reg = SkillRegistry.discover(tmp_path)
    assert len(reg) == 0
    assert len(reg.errors) == 1


def test_registry_bool_and_len(tmp_path):
    assert not SkillRegistry.discover(tmp_path)
    write_skill(tmp_path, "a", "name: a\ndescription: b")
    assert SkillRegistry.discover(tmp_path)
