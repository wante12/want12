"""领域事件定义。

这是 core 与所有 UI 层之间的唯一契约。

core 在对话过程中产出事件，UI 层（TUI / Web / Desktop）订阅并渲染。
core 不 import 任何 UI 模块，保证可被任意前端复用。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class EventType(str, Enum):
    """事件类型，供 UI 侧做分支渲染。"""

    ROUND_STARTED = "round_started"
    TEXT_DELTA = "text_delta"
    TOOL_CALL_STARTED = "tool_call_started"
    TOOL_CALL_FINISHED = "tool_call_finished"
    ROUND_FINISHED = "round_finished"
    ERROR = "error"


@dataclass(frozen=True)
class AgentEvent:
    """Agent 产出的单条事件。

    payload 内容随 EventType 变化：
        ROUND_STARTED        -> {"prompt": str}
        TEXT_DELTA           -> {"text": str}
        TOOL_CALL_STARTED    -> {"name": str, "arguments": dict}
        TOOL_CALL_FINISHED   -> {"name": str, "result": str}
        ROUND_FINISHED       -> {"content": str}
        ERROR                -> {"message": str}
    """

    type: EventType
    payload: dict[str, Any] = field(default_factory=dict)

    # ---- 便捷属性：让 UI 不必反复写 payload["..."] ----
    @property
    def text(self) -> str:
        return str(self.payload.get("text", ""))

    @property
    def tool_name(self) -> str:
        return str(self.payload.get("name", ""))
