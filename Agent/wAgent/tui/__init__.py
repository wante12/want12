"""tui 包：Textual 文本界面实现。

仅依赖 core 的公开接口（build_agent / AgentEvent）。
"""

from .app import AgentTUI

__all__ = ["AgentTUI"]
