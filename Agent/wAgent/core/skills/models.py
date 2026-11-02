"""Skill 数据模型。

按 Agent Skills 规范，一个 Skill 就是一个子目录，其中至少包含 SKILL.md，
SKILL.md 开头用 YAML Frontmatter 声明 name 与 description（两个必需字段）。

初始化阶段只保留元信息，不持有正文。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Skill:
    """一个已发现的 Skill 的元信息。"""

    #: frontmatter 里的 name（必需）
    name: str
    #: frontmatter 里的 description（必需）
    description: str
    #: Skill 目录
    path: Path
    #: SKILL.md 路径
    skill_file: Path
    #: frontmatter 的其余字段（version / layout 等），便于后续扩展
    extra: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return f"{self.name}: {self.description}"

    @property
    def short_description(self) -> str:
        """压平成单行，便于列表展示。"""
        return " ".join(self.description.split())


@dataclass(frozen=True)
class SkillLoadError:
    """一个加载失败的 Skill 子目录，用于向用户汇报。"""

    path: Path
    reason: str

    def __str__(self) -> str:
        return f"{self.path.name}: {self.reason}"
