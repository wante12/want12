"""上下文压缩。

流程（`/compact` 触发）：
    1. 归档原始上下文到 .agents/context/<id>.jsonl（必须成功）
    2. 用专用 Prompt 让 LLM 生成摘要
    3. 用「摘要 + 归档说明」替换历史消息，保留 System Prompt
    4. 失败则回滚，原上下文不受影响

压缩期间 Agent 处于「压缩状态」，禁止执行工具、禁止处理新任务。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .archive import ArchiveError, save_archive
from .tokens import count_messages_tokens, format_k

#: 压缩专用 Prompt（按需求给定）
COMPACT_PROMPT = """你是一名 AI Agent 的上下文管理助手。当前会话即将达到上下文窗口限制，需要将历史对话压缩为一份高质量的工作摘要，以便 Agent 在新的上下文中继续执行任务。

请认真阅读提供的历史上下文，提取对后续工作仍然有价值的信息，并生成一份约 5,000 Tokens 的 Markdown 摘要。

摘要应重点保留以下内容：

1. **用户目标与要求**：用户希望完成什么任务？有哪些必须遵守的约束、偏好和验收条件？
2. **已经完成的工作**：哪些任务已经完成？实现了哪些功能？获得了哪些已经验证的结果？
3. **当前工作状态**：Agent 正在处理什么任务？当前进展到哪一步？是否存在尚未解决的问题？
4. **关键技术信息**：保留重要的文件路径、函数名称、接口定义、配置项、执行命令、错误信息和必要的代码片段。
5. **关键决策与原因**：记录用户和 Agent 已经确定的技术方案，以及重要的设计取舍。
6. **下一步任务**：明确接下来应该执行的操作，以及需要继续验证的事项。

请遵守以下要求：

- 优先保留对后续任务有直接影响的信息，删除寒暄、重复讨论、过时的尝试和无关内容。
- 对已经验证的事实与尚未验证的推测作出明确区分。
- 不要将计划完成的任务描述为已经完成。
- 重要的文件路径、函数名称、配置名称和命令应保留准确原文。
- 对失败的尝试，只保留有助于避免重复错误的信息。
- 如果信息存在冲突，应优先保留用户最新确认的要求，并简要说明仍然存在的冲突。
- 如果某些历史细节无法在摘要中完整保留，可简要说明它们已保存到原始上下文归档中，后续可以通过 `recallContext` 工具重新检索。
- 使用清晰的 Markdown 结构输出摘要，不要附加解释或无关内容。

**最终目标：使一个从未阅读过原始对话的 Agent，仅凭这份摘要，就能够理解当前任务、继承关键决策，并继续开展工作。**"""

#: 归档说明模板
ARCHIVE_NOTICE = (
    "此前上下文已于 {time} 完成压缩，原始上下文保存在编号为 {archive_id} 的归档文件中。"
    "如需查找历史信息，请使用 recallContext 工具。"
)


class CompactError(Exception):
    """压缩失败。"""


@dataclass
class CompactResult:
    """压缩结果，供 UI 展示。"""

    archive_id: str
    archive_path: Path
    before_tokens: int
    after_tokens: int
    summary_tokens: int
    #: 压缩前的原始上下文（纯文本转录），供对比面板左侧显示
    before_text: str = ""
    #: 压缩后的摘要正文（不含归档说明），供对比面板右侧显示
    summary: str = ""

    def describe(self) -> str:
        return (
            f"上下文已压缩：{format_k(self.before_tokens)} → {format_k(self.after_tokens)}"
            f"（摘要 {format_k(self.summary_tokens)}）\n"
            f"归档编号：{self.archive_id}"
        )


def build_transcript(messages: list[dict[str, Any]]) -> str:
    """把消息列表渲染成便于模型阅读的纯文本。

    比直接塞 JSON 更省 token，也更容易被模型理解。
    """
    lines: list[str] = []
    for index, message in enumerate(messages):
        role = message.get("role", "unknown")
        content = message.get("content")

        if role == "system":
            # System Prompt 会保留，压缩时不必完整重复
            lines.append(f"### [{index}] system\n（系统提示，已保留，不参与压缩）")
            continue

        text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
        header = f"### [{index}] {role}"

        if role == "tool":
            call_id = message.get("tool_call_id", "")
            lines.append(f"{header} (tool_call_id={call_id})")
            lines.append(_clip(text, 8000))
            continue

        lines.append(header)
        if text:
            lines.append(_clip(text, 8000))

        for call in message.get("tool_calls") or []:
            function = call.get("function") or {}
            name = function.get("name", "")
            args = function.get("arguments", "")
            lines.append(f"- 调用工具 `{name}`，参数：{_clip(str(args), 2000)}")

        lines.append("")

    return "\n".join(lines)


def _clip(text: str, limit: int) -> str:
    text = text or ""
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n…（该条过长已截断，原长 {len(text)} 字符）"


class Compactor:
    """上下文压缩器。"""

    def __init__(self, client, project_root: Path | str | None = None) -> None:
        self._client = client
        self._project_root = Path(project_root) if project_root else None

    # ---------------------------------------------------------------- 主流程
    def compact(
        self,
        messages: list[dict[str, Any]],
        archive_id: str | None = None,
    ) -> tuple[list[dict[str, Any]], CompactResult]:
        """执行压缩，返回 (新的消息列表, 结果)。

        任何一步失败都抛 CompactError，调用方据此保留原上下文。
        """
        if not messages:
            raise CompactError("当前没有可压缩的上下文。")

        from .archive import generate_id

        archive_id = archive_id or generate_id()
        system_messages = [m for m in messages if m.get("role") == "system"]
        conversation = [m for m in messages if m.get("role") != "system"]

        if not conversation:
            raise CompactError("当前没有可压缩的对话内容（只有 System Prompt）。")

        before_tokens = count_messages_tokens(messages)

        # 1) 先归档——必须成功后才继续
        try:
            path = save_archive(
                archive_id,
                messages,
                self._project_root,
                meta={"reason": "compact", "before_tokens": before_tokens},
            )
        except ArchiveError as exc:
            raise CompactError(f"归档失败，已中止压缩（原上下文未改动）：{exc}") from exc

        # 2) 调 LLM 生成摘要
        transcript = build_transcript(conversation)
        try:
            summary = self._summarize(transcript)
        except CompactError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise CompactError(
                f"LLM 摘要生成失败（原上下文未改动，归档已保存：{archive_id}）：{exc}"
            ) from exc

        if not summary.strip():
            raise CompactError(
                f"LLM 返回了空摘要（原上下文未改动，归档已保存：{archive_id}）。"
            )

        # 3) 组装新上下文
        notice = ARCHIVE_NOTICE.format(
            time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"), archive_id=archive_id
        )
        summary_message = {
            "role": "user",
            "content": f"[上下文压缩摘要]\n\n{summary.strip()}\n\n---\n\n{notice}",
        }

        new_messages = list(system_messages) + [summary_message]
        after_tokens = count_messages_tokens(new_messages)

        return new_messages, CompactResult(
            archive_id=archive_id,
            archive_path=path,
            before_tokens=before_tokens,
            after_tokens=after_tokens,
            summary_tokens=count_messages_tokens([summary_message]),
            before_text=transcript,
            summary=summary.strip(),
        )

    # ---------------------------------------------------------------- 调用 LLM
    def _summarize(self, transcript: str) -> str:
        prompt = (
            f"{COMPACT_PROMPT}\n\n"
            "---\n\n"
            "以下是需要压缩的历史上下文：\n\n"
            f"{transcript}"
        )
        messages = [{"role": "user", "content": prompt}]

        complete = getattr(self._client, "complete", None)
        if callable(complete):
            result = complete(messages)
            if isinstance(result, str):
                return result
            return "".join(chunk.text for chunk in result)

        return "".join(chunk.text for chunk in self._client.stream(messages))


__all__ = [
    "ARCHIVE_NOTICE",
    "COMPACT_PROMPT",
    "CompactError",
    "CompactResult",
    "Compactor",
    "build_transcript",
]
