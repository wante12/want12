"""Skill 发现与元信息加载。

目录约定（项目根 = 程序启动时的工作目录）：
    <项目根>/.agents/skills/<skill-name>/SKILL.md

SKILL.md 结构：
    ---
    name: 技能名
    description: 技能说明
    ---
    正文……

按需求，初始化阶段**只读取 frontmatter**，正文既不解析也不保存在内存里：
读取时逐行扫描到结束分隔符就停止，文件的正文部分根本不会被读入。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from .models import Skill, SkillLoadError

#: 相对项目根的 Skill 目录
SKILLS_DIR = Path(".agents") / "skills"
#: 每个 Skill 子目录中必需的文件名
SKILL_FILE = "SKILL.md"
#: YAML frontmatter 分隔符
_FENCE = "---"
#: 读取 frontmatter 的行数上限，防止异常文件把内存吃满
_MAX_FRONTMATTER_LINES = 200


class SkillError(Exception):
    """Skill 解析失败。"""


def parse_frontmatter(text: str) -> dict[str, Any]:
    """解析 YAML frontmatter，返回字典。

    只负责解析已取到的 frontmatter 文本（不含分隔符）。
    """
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover
        raise SkillError("缺少 PyYAML，请执行 pip install pyyaml") from exc

    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise SkillError(f"YAML 解析失败：{exc}") from exc

    if data is None:
        raise SkillError("frontmatter 为空")
    if not isinstance(data, dict):
        raise SkillError("frontmatter 必须是键值映射")
    return data


def read_frontmatter(skill_file: Path) -> dict[str, Any]:
    """从 SKILL.md 只读出 frontmatter，正文部分不读入内存。"""
    lines: list[str] = []
    started = False

    try:
        with skill_file.open("r", encoding="utf-8") as fh:
            for index, raw in enumerate(fh):
                if index > _MAX_FRONTMATTER_LINES:
                    raise SkillError(
                        f"frontmatter 超过 {_MAX_FRONTMATTER_LINES} 行仍未结束"
                    )
                line = raw.rstrip("\r\n")
                if not started:
                    if line.strip() != _FENCE:
                        raise SkillError("SKILL.md 必须以 --- 开头的 YAML frontmatter 起始")
                    started = True
                    continue
                if line.strip() == _FENCE:
                    break
                lines.append(line)
            else:
                # 文件读完仍未遇到结束分隔符
                if started:
                    raise SkillError("frontmatter 缺少结束分隔符 ---")
    except OSError as exc:
        raise SkillError(f"读取失败：{exc}") from exc

    return parse_frontmatter("\n".join(lines))


def _require_text(meta: dict[str, Any], key: str) -> str:
    value = meta.get(key)
    if value is None:
        raise SkillError(f"缺少必需字段 {key}")
    if not isinstance(value, str):
        raise SkillError(f"字段 {key} 必须是字符串")
    text = value.strip()
    if not text:
        raise SkillError(f"字段 {key} 不能为空")
    return text


# ---------------------------------------------------------------- 按需加载
def read_body(skill_file: Path) -> str:
    """读取 SKILL.md 的正文部分（跳过 frontmatter）。

    与 read_frontmatter 相反：这里才真正读取正文，
    由 loadSkill 工具在模型明确需要时调用。
    """
    try:
        text = skill_file.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise SkillError(f"读取失败：{exc}") from exc

    lines = text.splitlines()
    if not lines or lines[0].strip() != _FENCE:
        raise SkillError("SKILL.md 缺少 frontmatter 起始符")

    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == _FENCE:
            return "\n".join(lines[index + 1:]).strip()
    raise SkillError("frontmatter 缺少结束分隔符 ---")


def load_body(skill: Skill) -> str:
    """加载某个 Skill 的完整正文。"""
    return read_body(skill.skill_file)


# ---------------------------------------------------------------- 文件定位
def _inside(path: Path, root: Path) -> bool:
    """path 是否落在 root 目录内（含 root 自身）。"""
    return path == root or root in path.parents


def _read_text_any(path: Path) -> str:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise SkillError(f"读取失败：{exc}") from exc

    for enc in ("utf-8", "gbk"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


@dataclass(frozen=True)
class FileResolution:
    """filename 的解析结果。

    命中唯一文件时 path 非空；出现多个同名文件时 candidates 非空，
    交给模型自己决定读哪个。
    """

    path: Path | None = None
    candidates: tuple[Path, ...] = ()

    @property
    def is_unique(self) -> bool:
        return self.path is not None

    @property
    def is_ambiguous(self) -> bool:
        return self.path is None and bool(self.candidates)


def resolve_skill_file(
    skill: Skill,
    filename: str,
    project_root: Path | None = None,
) -> FileResolution:
    """把 LLM 给的 filename 解析成 Skill 目录内的真实文件。

    解析顺序（先精确、后模糊）：
        1. 绝对路径（必须仍在 Skill 目录内）
        2. 相对于 Skill 目录的路径
        3. 相对于项目根的路径（必须仍在 Skill 目录内）
        4. 只给了文件名时：在 Skill 目录内递归搜索同名文件
           —— 唯一则直接命中，多个则返回候选让模型选择

    任何一步解析出的路径若逃出 Skill 目录，一律拒绝。
    """
    raw = (filename or "").strip()
    if not raw:
        raise SkillError("filename 不能为空")

    root = skill.path.resolve()
    candidate = Path(raw)

    # 1) 绝对路径：允许，但必须落在 Skill 目录内
    if candidate.is_absolute():
        target = candidate.resolve()
        if not _inside(target, root):
            raise SkillError(f"拒绝访问技能目录之外的文件：{filename}")
        if not target.exists():
            raise SkillError(f"文件不存在：{filename}")
        if target.is_dir():
            raise SkillError(_dir_hint(target, filename))
        return FileResolution(path=target)

    # 2) 相对 Skill 目录；解析后若逃出目录立刻拒绝
    by_skill = (root / raw).resolve()
    if not _inside(by_skill, root):
        raise SkillError(f"拒绝访问技能目录之外的文件：{filename}")
    if by_skill.is_file():
        return FileResolution(path=by_skill)

    # 3) 相对项目根（只有落在 Skill 目录内才接受）
    if project_root is not None:
        try:
            by_project = (Path(project_root) / raw).resolve()
        except OSError:
            by_project = None
        if by_project is not None and by_project.is_file() and _inside(by_project, root):
            return FileResolution(path=by_project)

    # 精确路径已确定指向 Skill 内但不存在时，直接报不存在，不再模糊搜索
    if (root / raw).is_dir():
        raise SkillError(_dir_hint(by_skill, filename))

    # 4) 只给文件名：递归搜索同名文件
    wanted = candidate.name
    matches = sorted(
        (p.resolve() for p in root.rglob("*") if p.is_file() and p.name == wanted),
        key=lambda p: str(p).lower(),
    )
    if len(matches) == 1:
        return FileResolution(path=matches[0])
    if len(matches) > 1:
        return FileResolution(candidates=tuple(matches))

    raise SkillError(f"在技能「{skill.name}」目录中找不到文件：{filename}")


def _dir_hint(target: Path, filename: str) -> str:
    try:
        names = sorted(p.name for p in target.iterdir())[:30]
    except OSError:
        names = []
    listing = "、".join(names) if names else "(空目录)"
    return f"{filename} 是一个目录，其中的文件有：{listing}"


def load_skill_file(skill: Skill, relative_path: str) -> str:
    """加载 Skill 目录内的单个文件（内部使用，要求唯一命中）。"""
    resolution = resolve_skill_file(skill, relative_path)
    if not resolution.is_unique:
        raise SkillError(f"存在多个同名文件：{relative_path}")
    return _read_text_any(cast(Path, resolution.path))


def load_skill(skill_dir: Path) -> Skill:
    """加载单个 Skill 目录的元信息。目录不合法时抛 SkillError。"""
    if not skill_dir.is_dir():
        raise SkillError("不是目录")

    skill_file = skill_dir / SKILL_FILE
    if not skill_file.is_file():
        raise SkillError(f"缺少 {SKILL_FILE}")

    meta = read_frontmatter(skill_file)
    name = _require_text(meta, "name")
    description = _require_text(meta, "description")

    extra = {k: v for k, v in meta.items() if k not in ("name", "description")}
    return Skill(
        name=name,
        description=description,
        path=skill_dir,
        skill_file=skill_file,
        extra=extra,
    )


def discover_skills(
    project_root: Path | str | None = None,
) -> tuple[list[Skill], list[SkillLoadError]]:
    """扫描 <项目根>/.agents/skills 下的每个子目录。

    返回 (成功加载的 Skill 列表, 失败的列表)。
    目录不存在时返回空结果，不视为错误——没有 Skill 也能正常使用。
    单个 Skill 出错不影响其他 Skill。
    """
    root = Path(project_root) if project_root else Path.cwd()
    skills_dir = root / SKILLS_DIR

    if not skills_dir.is_dir():
        return [], []

    skills: list[Skill] = []
    errors: list[SkillLoadError] = []
    seen: dict[str, Path] = {}

    try:
        candidates = sorted(p for p in skills_dir.iterdir() if p.is_dir())
    except OSError as exc:
        return [], [SkillLoadError(skills_dir, f"目录无法访问：{exc}")]

    for entry in candidates:
        try:
            skill = load_skill(entry)
        except SkillError as exc:
            errors.append(SkillLoadError(entry, str(exc)))
            continue
        # 重名时保留先扫描到的（目录名排序靠前者），并记录冲突
        if skill.name in seen:
            errors.append(
                SkillLoadError(entry, f"名称「{skill.name}」与 {seen[skill.name].name} 重复，已跳过")
            )
            continue
        seen[skill.name] = entry
        skills.append(skill)

    return skills, errors
