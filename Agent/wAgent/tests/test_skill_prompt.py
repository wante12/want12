"""Skill 注入 System Prompt 与 loadSkill 工具测试。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from core.agent import Agent  # noqa: E402
from core.config import AgentSettings  # noqa: E402
from core.llm.client import LLMClient, StreamChunk  # noqa: E402
from core.skills import (  # noqa: E402
    LOAD_SKILL_TOOL,
    SkillError,
    SkillRegistry,
    build_skills_prompt,
    compose_system_prompt,
    load_body,
    load_skill_file,
)
from core.tools.base import ToolRegistry  # noqa: E402
from core.tools.skill import LoadSkillTool, build_load_skill_tool  # noqa: E402


def write_skill(root: Path, dirname: str, frontmatter: str, body: str = "正文指令") -> Path:
    d = root / ".agents" / "skills" / dirname
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(f"---\n{frontmatter}\n---\n\n{body}\n", encoding="utf-8")
    return d


class EchoClient(LLMClient):
    def stream(self, messages, tools=None):
        return iter([StreamChunk(text="ok")])


@pytest.fixture
def reg(tmp_path):
    write_skill(tmp_path, "a", "name: alpha\ndescription: 甲技能", "ALPHA BODY")
    write_skill(tmp_path, "b", "name: beta\ndescription: |\n  多行\n  描述", "BETA BODY")
    return SkillRegistry.discover(tmp_path)


# ---------------------------------------------------------------- Prompt 构建
def test_prompt_lists_all_skills(reg):
    prompt = build_skills_prompt(reg)
    assert "You have access to the following skills:" in prompt
    assert "'alpha'" in prompt
    assert "'beta'" in prompt
    assert "甲技能" in prompt


def test_prompt_mentions_load_tool(reg):
    prompt = build_skills_prompt(reg)
    assert LOAD_SKILL_TOOL in prompt
    assert "load the full instructions" in prompt
    assert "additional files" in prompt


def test_prompt_flattens_multiline_description(reg):
    prompt = build_skills_prompt(reg)
    # 每个技能占一行，多行描述不应把清单撑开
    skill_lines = [ln for ln in prompt.splitlines() if ln.startswith("- '")]
    assert len(skill_lines) == 2


def test_prompt_empty_when_no_skills(tmp_path):
    empty = SkillRegistry.discover(tmp_path)
    assert build_skills_prompt(empty) == ""
    assert build_skills_prompt(None) == ""


def test_compose_keeps_base_when_no_skills(tmp_path):
    empty = SkillRegistry.discover(tmp_path)
    assert compose_system_prompt("BASE", empty) == "BASE"


def test_compose_appends_section(reg):
    out = compose_system_prompt("BASE", reg)
    assert out.startswith("BASE\n\n")
    assert "You have access" in out


# ---------------------------------------------------------------- 注入 Agent
def test_agent_uses_composed_prompt(reg):
    agent = Agent(
        AgentSettings(), EchoClient(), ToolRegistry(),
        system_prompt_extra=build_skills_prompt(reg),
    )
    assert "You have access to the following skills" in agent.system_prompt
    assert "alpha" in agent.system_prompt
    # 真正发给模型的 system 消息也包含技能段
    assert agent.history[0]["role"] == "system"
    assert "alpha" in agent.history[0]["content"]


def test_agent_reset_keeps_skill_section(reg):
    agent = Agent(
        AgentSettings(), EchoClient(), ToolRegistry(),
        system_prompt_extra=build_skills_prompt(reg),
    )
    list(agent.stream_reply("hi"))
    agent.reset()
    assert len(agent.history) == 1
    assert "alpha" in agent.history[0]["content"]


def test_agent_without_extra_has_plain_prompt():
    agent = Agent(AgentSettings(), EchoClient(), ToolRegistry())
    assert "You have access" not in agent.system_prompt


# ---------------------------------------------------------------- loadSkill
def test_tool_returns_body(reg):
    out = LoadSkillTool(reg).run("alpha")
    assert "ALPHA BODY" in out
    assert "alpha" in out


def test_tool_unknown_skill_lists_available(reg):
    out = LoadSkillTool(reg).run("nope")
    assert "未找到技能" in out
    assert "alpha" in out and "beta" in out


def test_tool_empty_name(reg):
    assert "name 不能为空" in LoadSkillTool(reg).run("   ")


def test_tool_loads_referenced_file(reg, tmp_path):
    ref = tmp_path / ".agents" / "skills" / "a" / "references"
    ref.mkdir(parents=True)
    (ref / "guide.md").write_text("附加内容", encoding="utf-8")

    out = LoadSkillTool(reg).run("alpha", "references/guide.md")
    assert "附加内容" in out
    assert "references/guide.md" in out


def test_tool_rejects_path_traversal(reg):
    out = LoadSkillTool(reg).run("alpha", "../../../secret.txt")
    assert "拒绝访问" in out


def test_tool_missing_file(reg):
    assert "找不到文件" in LoadSkillTool(reg).run("alpha", "references/none.md")


def test_tool_on_directory_lists_files(reg, tmp_path):
    ref = tmp_path / ".agents" / "skills" / "a" / "references"
    ref.mkdir(parents=True)
    (ref / "x.md").write_text("x", encoding="utf-8")
    out = LoadSkillTool(reg).run("alpha", "references")
    assert "是一个目录" in out
    assert "x.md" in out


def test_builder_returns_none_without_skills(tmp_path):
    empty = SkillRegistry.discover(tmp_path)
    assert build_load_skill_tool(empty) is None
    assert build_load_skill_tool(None) is None


def test_builder_returns_tool_with_skills(reg):
    tool = build_load_skill_tool(reg)
    assert tool is not None and tool.name == LOAD_SKILL_TOOL


# ---------------------------------------------------------------- 接线
def test_build_registry_registers_load_skill(tmp_path, reg):
    from core.app import build_registry

    with_skills = build_registry(skills=reg)
    assert LOAD_SKILL_TOOL in with_skills.names

    without = build_registry(skills=None)
    assert LOAD_SKILL_TOOL not in without.names


# ---------------------------------------------------------------- 底层加载
def test_load_body_strips_frontmatter(reg):
    skill = reg.get("alpha")
    body = load_body(skill)
    assert "ALPHA BODY" in body
    assert "name: alpha" not in body


def test_load_skill_file_ok(reg, tmp_path):
    f = tmp_path / ".agents" / "skills" / "a" / "note.md"
    f.write_text("hello", encoding="utf-8")
    assert load_skill_file(reg.get("alpha"), "note.md") == "hello"


def test_load_skill_file_escape(reg):
    with pytest.raises(SkillError, match="拒绝访问"):
        load_skill_file(reg.get("alpha"), "../b/SKILL.md")
