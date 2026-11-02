"""内置工具：createSkill（根据用户要求新建 Skill）。

在 <项目根>/.agents/skills/<name>/ 下生成符合 Agent Skills 规范的 SKILL.md。

参数：
    name          Skill 名称，统一规范为小写字母 + 数字 + 连字符
    skillContext  要写入 SKILL.md 的完整内容

行为约定：
    - 目录名与 frontmatter 的 name 保持一致
    - 已存在则报错，绝不覆盖
    - 只生成 SKILL.md；references/、scripts/ 等辅助目录
      由 LLM 继续调用 createDir / createFile 完成
"""

from __future__ import annotations

import re
from pathlib import Path

from ..skills.loader import SKILL_FILE, SKILLS_DIR, SkillError, read_frontmatter
from ..skills.registry import SkillRegistry
from .base import Tool

#: 名字长度上限（Agent Skills 规范）
MAX_NAME_LEN = 64
#: 合法字符：小写字母、数字、连字符
_NAME_RE = re.compile(r"^[a-z0-9-]+$")


def normalize_name(raw: str) -> tuple[str, list[str]]:
    """把用户给的名字规范化成 kebab-case。

    返回 (规范名, 改动说明列表)。中文等无法转换的字符会被丢弃，
    调用方可据此判断是否需要提示用户。
    """
    original = (raw or "").strip()
    notes: list[str] = []

    name = original.lower()
    if name != original:
        notes.append("转为小写")

    # 空格与下划线视为分隔符
    replaced = re.sub(r"[\s_]+", "-", name)
    if replaced != name:
        notes.append("空格/下划线转为连字符")
    name = replaced

    # 去掉非法字符
    cleaned = re.sub(r"[^a-z0-9-]", "", name)
    if cleaned != name:
        notes.append("移除了不合法的字符")
    name = cleaned

    # 压缩连续连字符、去掉首尾连字符
    squashed = re.sub(r"-{2,}", "-", name).strip("-")
    if squashed != name:
        notes.append("整理了多余的连字符")
    return squashed, notes


def validate_name(name: str) -> str | None:
    """校验规范名，返回错误信息或 None。"""
    if not name:
        return (
            "Skill 名称规范化后为空。名称只能包含小写字母、数字和连字符，"
            "例如 'doc-writer' 或 'pdf-summary'。"
        )
    if not _NAME_RE.match(name):
        return f"Skill 名称「{name}」只能包含小写字母、数字和连字符。"
    if name.startswith("-") or name.endswith("-") or "--" in name:
        return f"Skill 名称「{name}」不能以连字符开头/结尾，也不能有连续连字符。"
    if len(name) > MAX_NAME_LEN:
        return f"Skill 名称过长（{len(name)} 字符），上限 {MAX_NAME_LEN}。"
    return None


def render_skill_md(name: str, description: str, body: str) -> str:
    """拼出规范的 SKILL.md 文本。

    description 用 YAML 单引号标量，内部单引号双写转义，
    避免多行/冒号等特殊字符破坏 frontmatter。
    """
    safe_desc = description.replace("'", "''")
    body = (body or "").strip()
    return f"---\nname: {name}\ndescription: '{safe_desc}'\n---\n\n{body}\n"


def split_context(skill_context: str) -> tuple[str, str]:
    """从 skillContext 中拆出 (description, 正文)。

    约定：第一行非空文本作为 description，其余作为正文。
    若提供了 --- frontmatter，则沿用其中的 description。
    """
    text = (skill_context or "").strip()
    if not text:
        return "", ""

    # 已带 frontmatter：直接取其中的 description，正文去掉 frontmatter
    if text.startswith("---"):
        try:
            meta = read_frontmatter_text(text)
        except SkillError:
            meta = None
        if isinstance(meta, dict) and meta.get("description"):
            body = text.split("---", 2)[-1].strip()
            return str(meta["description"]).strip(), body

    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.strip():
            description = line.strip()
            body = "\n".join(lines[index + 1:]).strip()
            return description, body
    return "", ""


def read_frontmatter_text(text: str) -> dict:
    """从一段文本里解析 frontmatter（不落盘）。"""
    import yaml

    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise SkillError("没有 frontmatter")
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            data = yaml.safe_load("\n".join(lines[1:i]))
            if not isinstance(data, dict):
                raise SkillError("frontmatter 不是映射")
            return data
    raise SkillError("frontmatter 未闭合")


class CreateSkillTool(Tool):
    name = "createSkill"
    description = (
        "创建一个新的 Agent Skill。会在当前项目的 .agents/skills/ 下"
        "生成 <name>/SKILL.md（含 name、description 与正文）。"
        "name 会自动规范为小写字母、数字和连字符；已存在的技能不会被覆盖。"
        "若还需 references/、scripts/ 等辅助文件，请创建后继续调用 createDir / createFile。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Skill 名称，如 pdf-summary。将作为目录名与 frontmatter 的 name",
            },
            "skillContext": {
                "type": "string",
                "description": (
                    "要写入 SKILL.md 的完整内容。"
                    "第一行非空文本会作为 description，其余作为正文；"
                    "也可以直接提供带 YAML frontmatter 的完整 Markdown"
                ),
            },
        },
        "required": ["name", "skillContext"],
        "additionalProperties": False,
    }

    def __init__(
        self,
        registry: SkillRegistry | None = None,
        project_root: Path | None = None,
        tool_registry=None,
    ) -> None:
        self._registry = registry
        self._root = Path(project_root) if project_root else None
        # 可选：用于创建后补注册 loadSkill（原本没有技能时它不会被注册）
        self._tool_registry = tool_registry

    # ------------------------------------------------------------------ 入口
    def run(self, name: str, skillContext: str) -> str:
        raw = (name or "").strip()
        if not raw:
            return "创建失败：name 不能为空。"

        # 非英文名直接拒绝：规范化会丢掉中文字符，留下残名（如 PDF摘要 → pdf）
        if any(not ch.isascii() for ch in raw):
            return (
                f"创建失败：名称「{raw}」包含非英文字符，无法作为 Skill 目录名。\n"
                "Skill 目录名只能由小写字母、数字和连字符组成，"
                "请提供一个英文名称，例如 'pdf-summary'、'doc-writer'、'note-taker'。"
            )

        normalized, notes = normalize_name(raw)
        error = validate_name(normalized)
        if error:
            return f"创建失败：{error}"

        if not (skillContext or "").strip():
            return "创建失败：skillContext 不能为空，需要写入 SKILL.md 的正文内容。"

        description, body = split_context(skillContext)
        if not description:
            return "创建失败：无法从 skillContext 中解析出 description。"
        if "<" in description or ">" in description:
            return (
                "创建失败：description 不能包含尖括号 < >，"
                "请调整 skillContext 的第一行后重试。"
            )
        if not body:
            return (
                "创建失败：skillContext 只提供了 description，缺少正文。"
                "请在后面补充该技能的具体说明。"
            )

        root = self._root or Path.cwd()
        skills_dir = root / SKILLS_DIR
        target = skills_dir / normalized

        # 已存在则拒绝覆盖
        if target.exists():
            return (
                f"创建失败：技能「{normalized}」已存在（{target}），为避免覆盖原有内容已中止。\n"
                "如需修改，请先用 readFile 查看现有 SKILL.md，再用 editFile 更新；"
                "或换一个名称。"
            )

        try:
            skills_dir.mkdir(parents=True, exist_ok=True)
            target.mkdir()
            skill_file = target / SKILL_FILE
            skill_file.write_text(
                render_skill_md(normalized, description, body), encoding="utf-8"
            )
        except OSError as exc:
            # 失败时清理可能创建的空目录
            try:
                if target.exists() and not any(target.iterdir()):
                    target.rmdir()
            except OSError:
                pass
            return f"创建失败：{exc}"

        # 自校验：重新解析生成的 SKILL.md
        try:
            meta = read_frontmatter(skill_file)
            assert meta["name"] == normalized
        except Exception as exc:  # noqa: BLE001 生成即失败的情况极少，兜底
            return f"创建失败：生成的 SKILL.md 校验未通过（{exc}）。文件：{skill_file}"

        # 同步注册到当前会话，使 loadSkill 立刻可用（否则要重启才生效）
        registered_live = False
        if self._registry is not None:
            try:
                from ..skills.loader import load_skill

                skill = load_skill(target)
                self._registry.register(skill)
                registered_live = True

                # 原本没有技能时 loadSkill 未注册，这里补上
                if self._tool_registry is not None and "loadSkill" not in self._tool_registry.names:
                    from .skill import LoadSkillTool

                    self._tool_registry.register(LoadSkillTool(self._registry))
            except Exception:  # noqa: BLE001 注册失败不影响文件已创建
                pass

        lines = [
            f"已创建技能「{normalized}」",
            f"目录：{target}",
            f"文件：{skill_file}",
            f"description：{description}",
        ]
        if notes:
            lines.append(f"名称已规范化：{raw} → {normalized}（{('、'.join(notes))}）")
        lines.append("")
        lines.append("如需 references/、scripts/ 等辅助文件，请继续调用 createDir / createFile。")
        if registered_live:
            lines.append(
                f"该技能已加入当前会话，可立即用 loadSkill(name='{normalized}') 加载。"
            )
        else:
            lines.append("新技能会在下次启动 wAgent 时出现在技能清单中。")
        return "\n".join(lines)


def build_create_skill_tool(
    registry: SkillRegistry | None = None,
    project_root: Path | None = None,
    tool_registry=None,
) -> Tool:
    """始终注册：即使当前没有技能，也允许从零创建第一个。

    tool_registry 可选：创建成功后用它补注册 loadSkill。
    """
    root = project_root
    if root is None and registry is not None:
        candidate = getattr(registry, "root", None)
        # root 是 property，取到的是 Path；防御性地兼容直接传值的实现
        root = candidate() if callable(candidate) else candidate
    return CreateSkillTool(registry=registry, project_root=root, tool_registry=tool_registry)


__all__ = [
    "CreateSkillTool",
    "build_create_skill_tool",
    "normalize_name",
    "validate_name",
    "render_skill_md",
    "split_context",
]
