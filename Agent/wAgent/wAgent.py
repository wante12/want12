"""TUI 启动入口。

    python wAgent.py

只依赖 core 的 build_agent()，不接触任何 LLM 细节。
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
from tui.app import AgentTUI  # noqa: E402


def main() -> int:
    try:
        agent = build_agent()
    except ConfigError as exc:
        print(f"配置错误: {exc}", file=sys.stderr)
        print("请检查 config.ini 里的 [llm] base_url / api_key / model", file=sys.stderr)
        return 1

    AgentTUI(agent).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
