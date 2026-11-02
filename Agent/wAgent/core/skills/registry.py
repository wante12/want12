"""Skill 注册表。

初始化时把发现到的 Skill 元信息登记进来，供 UI 展示与后续调用阶段使用。
"""

from __future__ import annotations

from pathlib import Path

from .loader import discover_skills
from .models import Skill, SkillLoadError


class SkillRegistry:
    """按名称索引的 Skill 集合。"""

    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}
        self._errors: list[SkillLoadError] = []
        self._root: Path | None = None

    # ---------------------------------------------------------------- 装载
    @classmethod
    def discover(cls, project_root: Path | str | None = None) -> "SkillRegistry":
        """按项目根目录扫描并构造注册表。"""
        registry = cls()
        registry._root = Path(project_root) if project_root else Path.cwd()
        skills, errors = discover_skills(registry._root)
        for skill in skills:
            registry.register(skill)
        registry._errors.extend(errors)
        return registry

    def register(self, skill: Skill) -> None:
        if skill.name in self._skills:
            raise ValueError(f"Skill 重名: {skill.name}")
        self._skills[skill.name] = skill

    # ---------------------------------------------------------------- 查询
    @property
    def skills(self) -> list[Skill]:
        return list(self._skills.values())

    @property
    def names(self) -> list[str]:
        return list(self._skills)

    @property
    def errors(self) -> list[SkillLoadError]:
        """加载失败的 Skill 目录，便于提示用户修复。"""
        return list(self._errors)

    @property
    def root(self) -> Path | None:
        return self._root

    def get(self, name: str) -> Skill | None:
        return self._skills.get(name)

    def __len__(self) -> int:
        return len(self._skills)

    def __bool__(self) -> bool:
        return bool(self._skills)

    def __contains__(self, name: object) -> bool:
        return name in self._skills

    def __iter__(self):
        return iter(self._skills.values())

    # ---------------------------------------------------------------- 展示
    def specs(self) -> list[dict[str, str]]:
        """给 UI 用的简表：name + 压平的 description。"""
        return [
            {"name": s.name, "description": s.short_description}
            for s in self._skills.values()
        ]
