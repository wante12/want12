"""core 包：与界面完全无关的 Agent 业务内核。

对外只需要 `build_agent`。
"""

from .app import DEFAULT_CONFIG, Agent, AppConfig, build_agent, build_registry
from .events import AgentEvent, EventType

__all__ = [
    "Agent",
    "AgentEvent",
    "AppConfig",
    "EventType",
    "build_agent",
    "build_registry",
    "DEFAULT_CONFIG",
]
