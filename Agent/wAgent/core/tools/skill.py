"""内置工具：loadSkill（按需加载技能内容）。

System Prompt 里只给出 name + description，正文由模型在需要时主动加载。

参数：
    name      必需，Skill 名称
    filename  选填，Skill 内的文件路径或文件名
              - 只给 name：读取 SKILL.md 全文
              - 同时给 filename：只读该附加文件，不重复加载 SKILL.md

filename 支持绝对路径、项目相对路径、Skill 相对路径；
只给文件名时在 Skill 目录内递归搜索，命中唯一则读取，多个则返回候选。
所有读取都被限制在该 Skill 目录内。
"""

from __future__ import annotations

from ..skills.loader import (
    SkillError,
    _read_text_any,
    load_body,
    resolve_skill_file,
)
from ..skills.registry import SkillRegistry
from .base import Tool

#: 单个文件返回给模型的最大字符数，避免超大文件撑爆上下文
_MAX_CHARS = 100_000


class LoadSkillTool(Tool):
    name = "loadSkill"
    description = (
        "加载某个技能的完整说明。只传 name 时返回 SKILL.md 全文；"
        "同时传 filename 时读取该技能目录内的指定附加文件。"
        "filename 可用绝对路径、项目相对路径、技能相对路径，"
        "也可只给文件名（会在技能目录内递归查找；若有多个同名文件会返回候选路径供你选择）。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "技能名称，须与 System Prompt 中列出的一致",
            },
            "filename": {
                "type": "string",
                "description": (
                    "选填。要加载的技能内文件，可写相对技能目录的路径（如 references/guide.md）、"
                    "项目相对路径、绝对路径，或只写文件名（将递归查找）"
                ),
            },
        },
        "required": ["name"],
        "additionalProperties": False,
    }

    def __init__(self, registry: SkillRegistry) -> None:
        self._registry = registry

    # ------------------------------------------------------------------ 入口
    def run(self, name: str, filename: str | None = None) -> str:
        name = (name or "").strip()
        if not name:
            return f"加载失败：name 不能为空。可用技能：{self._available()}"

        skill = self._registry.get(name)
        if skill is None:
            return f"加载失败：未找到技能「{name}」。可用技能：{self._available()}"

        # 只给 name：返回 SKILL.md 全文
        if not filename or not str(filename).strip():
            try:
                return self._wrap(f"技能「{name}」的完整说明：", load_body(skill))
            except SkillError as exc:
                return f"加载失败：{exc}"

        # 给了 filename：只读该文件，不重复加载 SKILL.md
        try:
            resolution = resolve_skill_file(skill, str(filename), self._project_root())
        except SkillError as exc:
            return f"加载失败：{exc}"

        if resolution.is_ambiguous:
            return self._render_candidates(name, str(filename), resolution.candidates)

        try:
            content = _read_text_any(resolution.path)
        except SkillError as exc:
            return f"加载失败：{exc}"

        rel = self._relative(skill, resolution.path)
        return self._wrap(f"技能「{name}」的文件 {rel}：", content)

    # ------------------------------------------------------------------ 辅助
    def _available(self) -> str:
        return "、".join(self._registry.names) or "(无)"

    def _project_root(self):
        return getattr(self._registry, "root", None)

    @staticmethod
    def _relative(skill, path) -> str:
        """转成相对技能目录的路径，便于模型理解位置。"""
        try:
            return path.relative_to(skill.path.resolve()).as_posix()
        except ValueError:
            return str(path)

    def _render_candidates(self, name: str, filename: str, candidates) -> str:
        skill = self._registry.get(name)
        lines = [
            f"技能「{name}」目录中有多个名为「{filename}」的文件，"
            "请用 filename 参数指定要读取的路径：",
        ]
        for item in candidates:
            lines.append(f"- {self._relative(skill, item)}")
        return "\n".join(lines)

    @staticmethod
    def _wrap(header: str, content: str) -> str:
        content = (content or "").strip()
        if not content:
            return f"{header}\n\n(内容为空)"
        if len(content) > _MAX_CHARS:
            content = content[:_MAX_CHARS] + f"\n\n…（内容过长，已截断到 {_MAX_CHARS} 字符）"
        return f"{header}\n\n{content}"


def build_load_skill_tool(registry: SkillRegistry | None) -> Tool | None:
    """没有技能时不注册该工具，避免模型调用到空实现。"""
    if not registry or len(registry) == 0:
        return None
    return LoadSkillTool(registry)


__all__ = ["LoadSkillTool", "build_load_skill_tool"]
