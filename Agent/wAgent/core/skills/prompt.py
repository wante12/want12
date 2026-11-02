"""把已发现的 Skill 渲染成 System Prompt 片段。

只使用 name 与 description（初始化阶段拿到的元信息），
正文由 loadSkill 工具在模型需要时按需加载。
"""

from __future__ import annotations

from .registry import SkillRegistry

#: 引用 Skill 的工具名，需与 tools/skill.py 保持一致
LOAD_SKILL_TOOL = "loadSkill"


def build_skills_prompt(registry: SkillRegistry | None) -> str:
    """生成技能清单段落；没有技能时返回空串（不污染 Prompt）。"""
    if not registry or len(registry) == 0:
        return ""

    lines = ["You have access to the following skills:"]
    for skill in registry.skills:
        # 描述压平为单行，避免多行 YAML 块标量把清单撑开
        description = skill.short_description
        lines.append(f"- '{skill.name}': {description}")

    lines.append("")
    lines.append(
        f"Use the '{LOAD_SKILL_TOOL}' tool to load the full instructions of a skill "
        "when needed."
    )
    lines.append("You can also load additional files referenced by a skill.")
    lines.append(
        "Only load a skill when it is relevant to the current task; "
        "do not load every skill up front."
    )
    lines.append(
        "Skills work alongside your other tools: use the regular tools for "
        "files, commands and web access, and load a skill only for its task-specific guidance."
    )
    return "\n".join(lines)


def compose_system_prompt(base_prompt: str, registry: SkillRegistry | None) -> str:
    """把技能段落拼到基础 System Prompt 后面。"""
    section = build_skills_prompt(registry)
    if not section:
        return base_prompt
    return f"{base_prompt}\n\n{section}"
