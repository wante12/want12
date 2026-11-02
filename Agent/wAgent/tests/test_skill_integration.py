"""动态加载原则与工具协同的集成测试。

要证明的两件事：
1. Skill 正文只有在 LLM 调用 loadSkill 之后才进入对话上下文；
   在此之前，上下文里只有 name + description。
2. Agent 工作流没有被改动：Skill 与 RunCli / 文件工具等
   走同一条 registry.execute 通道，可混合调用。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from core.agent import Agent  # noqa: E402
from core.config import AgentSettings  # noqa: E402
from core.events import EventType  # noqa: E402
from core.llm.client import LLMClient, StreamChunk, ToolCallDelta  # noqa: E402
from core.skills import SkillRegistry, build_skills_prompt  # noqa: E402
from core.tools.base import ToolRegistry  # noqa: E402
from core.tools.skill import build_load_skill_tool  # noqa: E402

BODY_MARKER = "SECRET-SKILL-BODY-9f3a"


def write_skill(root: Path, dirname: str, name: str, desc: str, body: str) -> Path:
    d = root / ".agents" / "skills" / dirname
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {desc}\n---\n\n{body}\n", encoding="utf-8"
    )
    return d


class ScriptedClient(LLMClient):
    """按脚本依次返回：每项是若干 StreamChunk。"""

    def __init__(self, script: list[list[StreamChunk]]) -> None:
        self._script = list(script)
        self.seen_messages: list[list[dict]] = []

    def stream(self, messages, tools=None):
        self.seen_messages.append([dict(m) for m in messages])
        return iter(self._script.pop(0))


def call(name: str, args: dict, call_id: str = "c1") -> StreamChunk:
    import json

    return StreamChunk(
        tool_calls=[
            ToolCallDelta(
                index=0, id=call_id, name=name, arguments=json.dumps(args, ensure_ascii=False)
            )
        ]
    )


@pytest.fixture
def env(tmp_path):
    write_skill(tmp_path, "demo", "demo", "演示技能", BODY_MARKER)
    registry = SkillRegistry.discover(tmp_path)
    tools = ToolRegistry()
    tool = build_load_skill_tool(registry)
    assert tool is not None
    tools.register(tool)
    return tmp_path, registry, tools


def make_agent(env, script) -> Agent:
    _, registry, tools = env
    return Agent(
        AgentSettings(),
        ScriptedClient(script),
        tools,
        system_prompt_extra=build_skills_prompt(registry),
    )


# ---------------------------------------------------------------- 动态加载
def test_body_absent_from_system_prompt(env):
    """Prompt 里只有名称与描述，不含正文。"""
    _, registry, _ = env
    prompt = build_skills_prompt(registry)
    assert "demo" in prompt
    assert "演示技能" in prompt
    assert BODY_MARKER not in prompt


def test_body_absent_before_load_skill(env):
    """调用 loadSkill 之前，上下文里没有正文。"""
    agent = make_agent(env, [[StreamChunk(text="先不加载技能")]])
    list(agent.stream_reply("随便聊聊"))

    context = "\n".join(str(m.get("content")) for m in agent.history)
    assert BODY_MARKER not in context
    assert "演示技能" in context          # 元信息在


def test_body_present_after_load_skill(env):
    """调用 loadSkill 之后，正文才作为 tool 消息进入上下文。"""
    agent = make_agent(
        env,
        [
            [call("loadSkill", {"name": "demo"}, "c1")],
            [StreamChunk(text="已按技能说明处理")],
        ],
    )
    events = list(agent.stream_reply("执行技能"))

    finished = [e for e in events if e.type is EventType.TOOL_CALL_FINISHED]
    assert BODY_MARKER in finished[0].payload["result"]

    tool_messages = [m for m in agent.history if m["role"] == "tool"]
    assert len(tool_messages) == 1
    assert BODY_MARKER in tool_messages[0]["content"]


def test_model_sees_body_on_next_turn(env):
    """模型第二次请求时，上下文中才出现正文。"""
    agent = make_agent(
        env,
        [
            [call("loadSkill", {"name": "demo"}, "c1")],
            [StreamChunk(text="好")],
        ],
    )
    list(agent.stream_reply("go"))

    client = agent._client  # 测试内省
    first_messages, second_messages = client.seen_messages[0], client.seen_messages[1]
    assert BODY_MARKER not in str(first_messages)
    assert BODY_MARKER in str(second_messages)


# ---------------------------------------------------------------- 工具协同
def test_load_skill_coexists_with_run_cli(env):
    """同一轮里先 loadSkill 再 RunCli，两个工具都能正常执行。"""
    agent = make_agent(
        env,
        [
            [call("loadSkill", {"name": "demo"}, "c1")],
            [call("RunCli", {"command": "python", "args": ["-c", "print('CLI-OK')"]}, "c2")],
            [StreamChunk(text="都完成了")],
        ],
    )
    # 注册 RunCli 以证明混合调用
    from core.tools.cli import RunCliTool

    agent._registry.register(RunCliTool())

    events = list(agent.stream_reply("先加载技能再跑命令"))
    finished = {
        e.payload["name"]: e.payload["result"]
        for e in events
        if e.type is EventType.TOOL_CALL_FINISHED
    }

    assert BODY_MARKER in finished["loadSkill"]
    assert "CLI-OK" in finished["RunCli"]

    roles = [m["role"] for m in agent.history]
    assert roles.count("tool") == 2
    assert roles[-1] == "assistant"


def test_load_skill_then_read_file(env):
    """loadSkill 与文件工具并存：读技能文件后再用 readFile 读普通文件。"""
    from core.tools.filesystem import ReadFileTool

    project, registry, tools = env
    tools.register(ReadFileTool())
    plain = project / "note.txt"
    plain.write_text("普通文件内容", encoding="utf-8")

    agent = make_agent(
        env,
        [
            [call("loadSkill", {"name": "demo", "filename": "SKILL.md"}, "c1")],
            [call("readFile", {"path": str(plain)}, "c2")],
            [StreamChunk(text="读完")],
        ],
    )
    events = list(agent.stream_reply("读技能和普通文件"))
    results = [
        e.payload["result"] for e in events if e.type is EventType.TOOL_CALL_FINISHED
    ]
    assert any(BODY_MARKER in r for r in results)
    assert any("普通文件内容" in r for r in results)


def test_multiple_tools_in_one_assistant_turn(env):
    """模型一次请求多个工具调用时，逐个执行，顺序保持。"""
    from core.tools.cli import RunCliTool

    project, _, tools = env
    tools.register(RunCliTool())

    batch = StreamChunk(
        tool_calls=[
            ToolCallDelta(
                index=0, id="a", name="loadSkill", arguments='{"name":"demo"}'
            ),
            ToolCallDelta(
                index=1, id="b", name="RunCli",
                arguments='{"command":"python","args":["-c","print(1)"]}',
            ),
        ]
    )
    agent = make_agent(
        env, [[batch], [StreamChunk(text="done")]]
    )
    events = list(agent.stream_reply("一次调两个"))

    names = [e.payload["name"] for e in events if e.type is EventType.TOOL_CALL_STARTED]
    assert names == ["loadSkill", "RunCli"]


# ---------------------------------------------------------------- 工作流不变
def test_max_tool_rounds_still_enforced(env):
    """Skill 不改变轮次上限：一直请求工具会被截断。"""
    from core.tools.cli import RunCliTool

    _, _, tools = env
    tools.register(RunCliTool())

    loop = [
        [call("RunCli", {"command": "python", "args": ["-c", "print(1)"]}, f"c{i}")]
        for i in range(20)
    ]
    agent = Agent(
        AgentSettings(max_tool_rounds=2),
        ScriptedClient(loop),
        tools,
        system_prompt_extra=build_skills_prompt(env[1]),
    )
    with pytest.raises(RuntimeError, match="工具调用次数过多"):
        list(agent.stream_reply("无限调用"))

    # 失败后本轮回滚，只剩 system
    assert [m["role"] for m in agent.history] == ["system"]


def test_tool_error_does_not_break_workflow(env):
    """loadSkill 失败会自动回传错误文本，Agent 继续完成本轮。"""
    agent = make_agent(
        env,
        [
            [call("loadSkill", {"name": "不存在的技能"}, "c1")],
            [StreamChunk(text="没找到技能，我直接回答")],
        ],
    )
    events = list(agent.stream_reply("用个假技能"))
    finished = [e for e in events if e.type is EventType.TOOL_CALL_FINISHED]
    assert "未找到技能" in finished[0].payload["result"]
    assert events[-1].type is EventType.ROUND_FINISHED


def test_none_skills_keeps_agent_unchanged(tmp_path):
    """没有技能时，工作流与之前完全一致：13 个工具、无技能段。"""
    from core.app import build_registry

    registry = build_registry(skills=None)
    assert "loadSkill" not in registry.names
    agent = Agent(AgentSettings(), ScriptedClient([[StreamChunk(text="hi")]]), registry)
    assert "You have access" not in agent.system_prompt
    list(agent.stream_reply("hi"))
    assert [m["role"] for m in agent.history] == ["system", "user", "assistant"]
