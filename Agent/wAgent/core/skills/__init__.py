"""Skill 子系统：按 Agent Skills 规范发现与注册本地技能。

    <项目根>/.agents/skills/<skill>/SKILL.md

初始化阶段只加载 name 与 description，不读取正文；
正文由 loadSkill 工具按需加载。
"""

from .loader import (
    SKILLS_DIR,
    FileResolution,
    SkillError,
    discover_skills,
    load_body,
    load_skill,
    load_skill_file,
    parse_frontmatter,
    read_body,
    read_frontmatter,
    resolve_skill_file,
)
from .models import Skill, SkillLoadError
from .prompt import LOAD_SKILL_TOOL, build_skills_prompt, compose_system_prompt
from .registry import SkillRegistry

__all__ = [
    "SKILLS_DIR",
    "LOAD_SKILL_TOOL",
    "FileResolution",
    "Skill",
    "SkillError",
    "SkillLoadError",
    "SkillRegistry",
    "build_skills_prompt",
    "compose_system_prompt",
    "discover_skills",
    "load_body",
    "load_skill",
    "load_skill_file",
    "parse_frontmatter",
    "read_body",
    "read_frontmatter",
    "resolve_skill_file",
]
