"""上下文压缩、归档与检索的测试。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from core.agent.engine import Agent  # noqa: E402
from core.config import AgentSettings  # noqa: E402
from core.context import (  # noqa: E402
    CompactError,
    Compactor,
    ContextUsage,
    RecallContextTool,
    archive_path,
    context_window_for,
    count_messages_tokens,
    count_text_tokens,
    generate_id,
    list_archives,
    read_archive,
    save_archive,
)
from core.context.archive import ArchiveError  # noqa: E402
from core.context.compactor import ARCHIVE_NOTICE, COMPACT_PROMPT  # noqa: E402
from core.context.recall import split_keywords  # noqa: E402
from core.llm.client import LLMClient, StreamChunk  # noqa: E402
from core.tools.base import ToolRegistry  # noqa: E402


class FakeClient(LLMClient):
    """返回固定摘要的假客户端。"""

    def __init__(self, summary: str = "# 摘要\n\n用户想要做某事。", fail: bool = False) -> None:
        self.summary = summary
        self.fail = fail
        self.calls: list = []

    def stream(self, messages, tools=None):
        self.calls.append(messages)
        return iter([StreamChunk(text="ok")])

    def complete(self, messages, tools=None):
        self.calls.append(messages)
        if self.fail:
            raise RuntimeError("模拟 LLM 失败")
        return self.summary


def sample_messages() -> list[dict]:
    return [
        {"role": "system", "content": "你是助手"},
        {"role": "user", "content": "帮我查住院中的宠物"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "c1",
                    "type": "function",
                    "function": {"name": "list_pets", "arguments": '{"status":"住院中"}'},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "c1", "content": "咪咪 住院中 猫瘟"},
        {"role": "assistant", "content": "查到 1 只：咪咪"},
    ]


# ---------------------------------------------------------------- token 估算
def test_count_text_tokens_cjk():
    assert count_text_tokens("你好世界") == 4


def test_count_text_tokens_ascii():
    assert count_text_tokens("abcd") == 1
    assert count_text_tokens("abcde") == 2


def test_count_messages_includes_tool_calls():
    with_tool = [sample_messages()[2]]
    without = [{"role": "assistant", "content": None}]
    assert count_messages_tokens(with_tool) > count_messages_tokens(without)


@pytest.mark.parametrize(
    "model,expect_default",
    [
        ("deepseek-chat", False),
        ("deepseek-chat-0324", False),
        ("gpt-4o", False),
        ("unknown-model-xyz", True),
        ("", True),
    ],
)
def test_context_window_lookup(model, expect_default):
    window, is_default = context_window_for(model)
    assert window > 0
    assert is_default is expect_default


# ---------------------------------------------------------------- 用量
def test_usage_prefers_api_tokens():
    messages = [{"role": "user", "content": "短"}]
    usage = ContextUsage.compute(messages, None, "deepseek-chat", api_prompt_tokens=50000)
    assert usage.used == 50000
    assert usage.measured_by_api is True


def test_usage_falls_back_to_estimate():
    messages = [{"role": "user", "content": "x" * 400}]
    usage = ContextUsage.compute(messages, None, "deepseek-chat")
    assert usage.measured_by_api is False
    assert usage.used > 0


def test_usage_includes_tools():
    messages = [{"role": "user", "content": "hi"}]
    tools = [{"type": "function", "function": {"name": "x", "description": "y" * 200}}]
    without = ContextUsage.compute(messages, None, "deepseek-chat")
    with_tools = ContextUsage.compute(messages, tools, "deepseek-chat")
    assert with_tools.used > without.used


def test_usage_threshold_at_70_percent():
    window, _ = context_window_for("deepseek-chat")
    under = ContextUsage(used=int(window * 0.69), window=window,
                         window_is_default=False, measured_by_api=True)
    over = ContextUsage(used=int(window * 0.71), window=window,
                        window_is_default=False, measured_by_api=True)
    assert not under.needs_compact
    assert over.needs_compact


def test_usage_label_shows_default():
    usage = ContextUsage(used=1024, window=128 * 1024,
                         window_is_default=True, measured_by_api=False)
    assert "默认" in usage.label()


# ---------------------------------------------------------------- 归档
def test_save_and_read_archive(tmp_path):
    archive_id = "20261022-153000"
    path = save_archive(archive_id, sample_messages(), tmp_path)
    assert path.is_file()
    assert path.name == f"{archive_id}.jsonl"

    records = read_archive(archive_id, tmp_path)
    assert records[0]["type"] == "meta"
    bodies = [r for r in records if r.get("type") != "meta"]
    assert len(bodies) == len(sample_messages())
    assert bodies[0]["role"] == "system"


def test_archive_preserves_tool_data(tmp_path):
    archive_id = "20261022-153001"
    save_archive(archive_id, sample_messages(), tmp_path)
    records = read_archive(archive_id, tmp_path)

    assistant = next(r for r in records if r.get("role") == "assistant" and r.get("tool_calls"))
    assert assistant["tool_calls"][0]["function"]["name"] == "list_pets"

    tool_msg = next(r for r in records if r.get("role") == "tool")
    assert tool_msg["tool_call_id"] == "c1"
    assert "咪咪" in tool_msg["content"]


def test_archive_preserves_order(tmp_path):
    archive_id = "20261022-153002"
    save_archive(archive_id, sample_messages(), tmp_path)
    records = [r for r in read_archive(archive_id, tmp_path) if r.get("type") != "meta"]
    assert [r["seq"] for r in records] == list(range(len(sample_messages())))
    assert [r["role"] for r in records] == [m["role"] for m in sample_messages()]


def test_list_archives_sorted_newest_first(tmp_path):
    for aid in ("20261022-100000", "20261023-100000", "20261021-100000"):
        save_archive(aid, sample_messages(), tmp_path)
    assert list_archives(tmp_path)[0] == "20261023-100000"


def test_bad_archive_id_rejected(tmp_path):
    with pytest.raises(ArchiveError):
        archive_path("bad id", tmp_path)


def test_generate_id_format():
    assert len(generate_id()) == len("20261022-153000")
    assert generate_id()[8] == "-"


# ---------------------------------------------------------------- 压缩
def test_compact_success(tmp_path):
    client = FakeClient()
    compactor = Compactor(client, tmp_path)
    new_messages, result = compactor.compact(sample_messages())

    assert result.archive_id
    assert archive_path(result.archive_id, tmp_path).is_file()
    assert len(new_messages) == 2                    # system + 摘要
    assert new_messages[0]["role"] == "system"
    assert new_messages[0]["content"] == "你是助手"
    assert "上下文压缩摘要" in new_messages[1]["content"]


def test_compact_appends_archive_notice(tmp_path):
    compactor = Compactor(FakeClient(), tmp_path)
    new_messages, result = compactor.compact(sample_messages())
    content = new_messages[1]["content"]
    assert result.archive_id in content
    assert "recallContext" in content
    assert "完成压缩" in content


def test_compact_uses_dedicated_prompt(tmp_path):
    client = FakeClient()
    compactor = Compactor(client, tmp_path)
    compactor.compact(sample_messages())

    prompt = client.calls[0][0]["content"]
    assert "上下文管理助手" in prompt
    assert "5,000 Tokens" in prompt
    assert "recallContext" in prompt


def test_compact_empty_raises(tmp_path):
    with pytest.raises(CompactError):
        Compactor(FakeClient(), tmp_path).compact([])


def test_compact_system_only_raises(tmp_path):
    with pytest.raises(CompactError, match="只有 System Prompt"):
        Compactor(FakeClient(), tmp_path).compact([{"role": "system", "content": "x"}])


def test_compact_llm_failure_keeps_original(tmp_path):
    original = sample_messages()
    compactor = Compactor(FakeClient(fail=True), tmp_path)
    with pytest.raises(CompactError, match="摘要生成失败"):
        compactor.compact(original)
    # 原消息列表未被修改
    assert original[0]["role"] == "system"
    assert len(original) == 5


def test_compact_empty_summary_raises(tmp_path):
    with pytest.raises(CompactError, match="空摘要"):
        Compactor(FakeClient(summary="   "), tmp_path).compact(sample_messages())


# ---------------------------------------------------------------- recallContext
def test_recall_finds_content(tmp_path):
    save_archive("20261022-120000", sample_messages(), tmp_path)
    tool = RecallContextTool(tmp_path)
    out = tool.run("咪咪")
    assert "咪咪" in out
    assert "20261022-120000" in out


def test_recall_specific_archive(tmp_path):
    save_archive("20261022-120000", sample_messages(), tmp_path)
    other = [{"role": "user", "content": "另一个话题：猫粮"}]
    save_archive("20261023-120000", other, tmp_path)

    tool = RecallContextTool(tmp_path)
    out = tool.run("咪咪", id="20261022-120000")
    assert "咪咪" in out
    out2 = tool.run("咪咪", id="20261023-120000")
    assert "未" in out2 and "咪咪" in out2   # 提示未找到


def test_recall_searches_all_when_no_id(tmp_path):
    save_archive("20261022-120000", [{"role": "user", "content": "苹果"}], tmp_path)
    save_archive("20261023-120000", [{"role": "user", "content": "香蕉"}], tmp_path)
    tool = RecallContextTool(tmp_path)
    out = tool.run("香蕉")
    assert "20261023-120000" in out


def test_recall_missing_archive(tmp_path):
    tool = RecallContextTool(tmp_path)
    out = tool.run("x", id="20990101-000000")
    assert "找不到归档" in out


def test_recall_no_archives(tmp_path):
    out = RecallContextTool(tmp_path).run("任意")
    assert "还没有任何上下文归档" in out


def test_recall_empty_text(tmp_path):
    assert "不能为空" in RecallContextTool(tmp_path).run("   ")


def test_recall_result_length_bounded(tmp_path):
    # 造一个很大的归档
    big = [{"role": "user", "content": ("关键词 " * 2000)} for _ in range(5)]
    save_archive("20261022-130000", big, tmp_path)
    out = RecallContextTool(tmp_path).run("关键词")
    assert len(out) < 6000            # 有长度上限


def test_split_keywords():
    assert split_keywords("宠物 医院,住院中") == ["宠物", "医院", "住院中"]


def test_recall_registered_by_default(tmp_path):
    from core.app import build_registry

    registry = build_registry(project_root=tmp_path)
    assert "recallContext" in registry.names


# ---------------------------------------------------------------- Agent 集成
class EchoClient(LLMClient):
    def stream(self, messages, tools=None):
        return iter([StreamChunk(text="回答")])


def make_agent() -> Agent:
    return Agent(AgentSettings(), EchoClient(), ToolRegistry(), model_name="deepseek-chat")


def test_agent_blocks_while_compacting():
    agent = make_agent()
    agent.set_compacting(True)
    with pytest.raises(RuntimeError, match="正在压缩上下文"):
        list(agent.stream_reply("hi"))


def test_agent_resumes_after_compacting():
    agent = make_agent()
    agent.set_compacting(True)
    agent.set_compacting(False)
    events = list(agent.stream_reply("hi"))
    assert events


def test_replace_context_keeps_own_system_prompt():
    agent = make_agent()
    original = agent.system_prompt
    agent.replace_context([
        {"role": "system", "content": "伪造的 system"},
        {"role": "user", "content": "摘要内容"},
    ])
    assert agent.history[0]["content"] == original
    assert len(agent.history) == 2


def test_agent_context_usage_available():
    agent = make_agent()
    usage = agent.context_usage()
    assert usage.window > 0
    assert usage.used > 0


def test_round_finished_reports_context():
    from core.events import EventType

    agent = make_agent()
    events = list(agent.stream_reply("hi"))
    finished = [e for e in events if e.type is EventType.ROUND_FINISHED][0]
    assert "context_used" in finished.payload
    assert "context_window" in finished.payload
    assert "context_warn" in finished.payload
