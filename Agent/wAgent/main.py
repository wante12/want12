"""TUI 启动入口。

    python main.py

启动流程：
    1. 确保 config.ini 存在（缺失则生成完整模板，并提示用户修改后重启）
    2. 以当前工作目录为项目根，扫描 .agents/skills
    3. 注入 AGENTS.md 到会话历史（一次注入）
    4. MCP 后台异步连接（先进入界面，连上后动态刷新）
    5. 交给 TUI 展示

只依赖 core 的公开接口，不接触 LLM 细节。
"""

from __future__ import annotations

import sys
from pathlib import Path

# 让脚本在任意工作目录下都能 import 本项目
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from core import build_agent  # noqa: E402
from core.config import (  # noqa: E402
    AppConfig,
    ConfigError,
    ensure_config_file,
    is_mock_config,
)
from core.mcp import build_mcp_manager  # noqa: E402
from core.session import SessionManager  # noqa: E402
from core.skills import SkillRegistry  # noqa: E402
from tui.app import AgentTUI  # noqa: E402

#: 配置文件名（放在程序目录，不在项目目录）
CONFIG_NAME = "config.ini"


def config_path() -> Path:
    """配置文件位置：程序所在目录。"""
    return BASE_DIR / CONFIG_NAME


def load_skills(project_root: Path | None = None) -> SkillRegistry:
    """按 Agent Skills 规范扫描 Skill。

    项目根默认为程序启动时的工作目录；只读取 name / description，
    单个 Skill 解析失败不会影响启动。
    """
    return SkillRegistry.discover(project_root or Path.cwd())


def load_mcp(project_root: Path | None = None):
    """按项目根的 .mcp.json 连接 MCP Server（同步版本，供测试与脚本使用）。"""
    root = Path(project_root) if project_root else Path.cwd()
    return build_mcp_manager(project_root=root)


def _boot_message(new_config: bool, mock: bool, path: Path) -> str:
    """生成启动提示的正文（Markdown）。"""
    if new_config:
        return (
            f"### 已创建新的配置文件\n\n"
            f"`{path}`\n\n"
            "里面填的是**示例信息**，还不能直接用。请按下面步骤操作：\n\n"
            "1. 用编辑器打开上面的文件\n"
            "2. 把 `[llm]` 段的 `api_key` 换成你的真实密钥\n"
            "3. 如有需要，调整 `base_url` 与 `model`\n"
            "4. **保存后重新启动 wAgent**\n\n"
            "> 也可以顺手填写 `[search]` 段的 `baidu_qianfan_api_key`，"
            "让 `searchWeb` 工具可用。\n\n"
            "关闭本提示后，wAgent 会退出。"
        )
    return (
        f"### 请在配置文件中填写真实的 API Key\n\n"
        f"`{path}`\n\n"
        "当前 `[llm] api_key` 仍是示例值，请求会失败。请修改后重新启动 wAgent。"
    )


def main() -> int:
    # ---------------------------------------------------------------- 配置
    path = config_path()
    path, created = ensure_config_file(path)

    boot_notice: tuple[str, str] | None = None
    try:
        cfg = AppConfig.load(path)
    except ConfigError as exc:
        print(f"配置错误: {exc}", file=sys.stderr)
        print(f"请检查 {path} 里的 [llm] base_url / api_key / model", file=sys.stderr)
        return 1

    mock = is_mock_config(cfg)
    if created or mock:
        boot_notice = ("需要配置 API Key", _boot_message(created, mock, path))

    project_root = Path.cwd()

    # ---------------------------------------------------------------- 技能
    skills = load_skills(project_root)
    for error in skills.errors:
        print(f"[Skill 跳过] {error}", file=sys.stderr)

    # ---------------------------------------------------------------- 会话
    sessions = SessionManager(
        project_root=project_root,
        subdir=cfg.session.dir,
        agents_md_name=cfg.session.agents_md,
        autosave=cfg.session.autosave,
    )

    # ---------------------------------------------------------------- MCP
    # 异步模式交给 TUI 后台连接；同步模式在这里连好
    mcp = build_mcp_manager(
        project_root=project_root,
        filename=cfg.mcp.filename,
        connect_timeout=cfg.mcp.connect_timeout,
        call_timeout=cfg.mcp.call_timeout,
        prefix_mode=cfg.mcp.prefix_mode,
        async_load=cfg.mcp.async_load,
    )
    if not cfg.mcp.async_load:
        for status in mcp.statuses:
            stream = sys.stdout if status.connected else sys.stderr
            print(f"[MCP] {status}", file=stream)

    # ---------------------------------------------------------------- Agent
    try:
        agent = build_agent(
            path,
            skills=skills,
            mcp=None if mcp.async_load else mcp,
            project_root=project_root,
            max_tool_rounds=cfg.agent.max_tool_rounds,
        )
    except ConfigError as exc:
        print(f"配置错误: {exc}", file=sys.stderr)
        mcp.close()
        return 1

    # AGENTS.md：一次注入，全程复用
    injected = None
    if boot_notice is None:
        try:
            injected = sessions.prepare_agents_md(agent)
        except Exception as exc:  # noqa: BLE001
            print(f"[AGENTS.md] 注入失败: {exc}", file=sys.stderr)
    if injected:
        print(f"[会话] {injected}", file=sys.stdout)

    # ---------------------------------------------------------------- TUI
    try:
        tui = AgentTUI(
            agent,
            config_path=path,
            skills=skills,
            mcp=mcp,
            project_root=project_root,
            sessions=sessions,
            boot_notice=boot_notice,
            mcp_async=cfg.mcp.async_load,
        )
        tui._app_config = cfg
        tui.run()
    finally:
        # 退出时自动保存会话
        try:
            sessions.autosave(agent)
        except Exception:  # noqa: BLE001
            pass
        mcp.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
