"""TUI 启动入口。

    python main.py

启动时以当前工作目录为项目根，扫描 .agents/skills 下的 Skill 元信息，
然后交给 TUI 展示。只依赖 core 的公开接口，不接触 LLM 细节。
"""

from __future__ import annotations

import sys
from pathlib import Path

# 让脚本在任意工作目录下都能 import 本项目
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from core import build_agent  # noqa: E402
from core.config import ConfigError  # noqa: E402
from core.mcp import build_mcp_manager  # noqa: E402
from core.skills import SkillRegistry  # noqa: E402
from tui.app import AgentTUI  # noqa: E402

#: 每轮会话调用模型的总次数上限
MAX_MODEL_CALLS_PER_ROUND = 20
#: 引擎按「工具轮数 + 1」循环，故传 19 使总调用次数正好为 20
MAX_TOOL_ROUNDS = MAX_MODEL_CALLS_PER_ROUND - 1


def load_skills(project_root: Path | None = None) -> SkillRegistry:
    """按 Agent Skills 规范扫描 Skill。

    项目根默认为程序启动时的工作目录；只读取 name / description，
    单个 Skill 解析失败不会影响启动。
    """
    return SkillRegistry.discover(project_root or Path.cwd())


def load_mcp(project_root: Path | None = None):
    """按项目根的 .mcp.json 连接 MCP Server。

    连接失败只会记录在 manager.statuses / issues 里，不影响 wAgent 启动。
    """
    root = Path(project_root) if project_root else Path.cwd()
    return build_mcp_manager(project_root=root)


def main() -> int:
    skills = load_skills()
    for error in skills.errors:
        print(f"[Skill 跳过] {error}", file=sys.stderr)

    mcp = load_mcp()
    for status in mcp.statuses:
        stream = sys.stdout if status.connected else sys.stderr
        print(f"[MCP] {status}", file=stream)
    for issue in mcp.issues:
        print(f"[MCP 配置] {issue}", file=sys.stderr)

    try:
        agent = build_agent(skills=skills, mcp=mcp, max_tool_rounds=MAX_TOOL_ROUNDS)
    except ConfigError as exc:
        print(f"配置错误: {exc}", file=sys.stderr)
        print("请检查 config.ini 里的 [llm] base_url / api_key / model", file=sys.stderr)
        mcp.close()
        return 1

    try:
        AgentTUI(agent, skills=skills, mcp=mcp).run()
    finally:
        mcp.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
