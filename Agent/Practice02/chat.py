import configparser
import json
import os
import subprocess
import sys
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE_DIR)

# Practice01 使用的 openai 依赖目录；如果已经用 pip 安装，可以删掉这段。
OPENAI_PATH = r"D:\openai"
if os.path.isdir(OPENAI_PATH):
    sys.path.insert(0, OPENAI_PATH)

from openai import OpenAI

TYPING_DELAY = 0.015  # 每个字符之间的间隔（秒）
MAX_TOOL_ROUNDS = 5

SYSTEM_PROMPT = (
    "你是一个可以调用工具的助手。"
    "当用户询问当前日期、时间、今天是几号或现在几点时，"
    "必须调用 getDate 工具获取当前电脑的日期和时间，不要自行猜测。"
)

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "getDate",
            "description": "获取当前电脑本地的日期和时间。",
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    }
]


def get_date() -> str:
    """调用本机 date 命令获取日期和时间，不使用 Python 的日期时间 API。"""
    if os.name == "nt":
        # Windows 的 date /T 只显示日期，time /T 显示时间。
        # 两个都是本机命令，日期和时间都不是用 Python 计算出来的。
        command = ["cmd", "/c", "date /T & time /T"]
    else:
        # Linux / macOS 的 date 命令本身就会输出日期和时间。
        command = ["date"]

    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        errors="replace",
        timeout=10,
    )
    output = (result.stdout or "").strip()
    error = (result.stderr or "").strip()
    if result.returncode != 0:
        raise RuntimeError(error or output or "date 命令执行失败")
    if not output:
        raise RuntimeError(error or "date 命令没有输出")
    return output


TOOL_HANDLERS = {"getDate": get_date}


def execute_tool_call(tool_call: dict) -> str:
    name = tool_call.get("function", {}).get("name", "")
    arguments_text = tool_call.get("function", {}).get("arguments") or "{}"

    try:
        arguments = json.loads(arguments_text)
    except json.JSONDecodeError as exc:
        return f"工具参数解析失败: {exc}"

    handler = TOOL_HANDLERS.get(name)
    if handler is None:
        return f"未知工具: {name}"

    try:
        return str(handler(**arguments))
    except Exception as exc:
        return f"工具 {name} 执行失败: {exc}"


def stream_completion(messages):
    """流式请求模型，返回 (文本内容, 工具调用列表)。"""
    stream = client.chat.completions.create(
        model=cfg["llm"]["model"],
        messages=messages,
        tools=TOOLS,
        tool_choice="auto",
        stream=True,
    )

    content_parts = []
    tool_calls = {}

    for chunk in stream:
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta

        piece = delta.content
        if piece:
            content_parts.append(piece)
            for ch in piece:
                print(ch, end="", flush=True)
                time.sleep(TYPING_DELAY)

        for tc in delta.tool_calls or []:
            index = tc.index if tc.index is not None else 0
            entry = tool_calls.setdefault(
                index,
                {
                    "id": "",
                    "type": "function",
                    "function": {"name": "", "arguments": ""},
                },
            )
            if tc.id:
                entry["id"] = tc.id
            if tc.type:
                entry["type"] = tc.type

            function = tc.function
            if function:
                if function.name:
                    entry["function"]["name"] += function.name
                if function.arguments:
                    entry["function"]["arguments"] += function.arguments

    return "".join(content_parts), [tool_calls[i] for i in sorted(tool_calls)]


cfg = configparser.ConfigParser()
config_path = os.path.join(BASE_DIR, "config.ini")
if not cfg.read(config_path, encoding="utf-8"):
    raise FileNotFoundError(f"找不到配置文件: {config_path}")

client = OpenAI(
    base_url=cfg["llm"]["base_url"],
    api_key=cfg["llm"]["api_key"],
)

messages = [{"role": "system", "content": SYSTEM_PROMPT}]


def chat_once(user_prompt: str) -> None:
    """完成一轮用户对话，必要时自动执行 getDate 工具。"""
    start_len = len(messages)
    messages.append({"role": "user", "content": user_prompt})
    print("--")

    try:
        for _ in range(MAX_TOOL_ROUNDS + 1):
            content, tool_calls = stream_completion(messages)

            if tool_calls:
                messages.append(
                    {
                        "role": "assistant",
                        "content": content or None,
                        "tool_calls": tool_calls,
                    }
                )

                for tool_call in tool_calls:
                    name = tool_call.get("function", {}).get("name", "")
                    print(f"\n[调用工具: {name}]")
                    result = execute_tool_call(tool_call)
                    print(f"[工具返回] {result}")
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call["id"],
                            "content": result,
                        }
                    )
                continue

            messages.append({"role": "assistant", "content": content})
            print()
            return

        raise RuntimeError("工具调用次数过多，已停止本轮对话。")
    except BaseException:
        # 本轮失败或被 Ctrl+C 中断时，回滚本轮消息，保持上下文干净。
        del messages[start_len:]
        raise


while True:
    try:
        prompt = input("Please input your prompt ")
    except (EOFError, KeyboardInterrupt):
        break

    try:
        chat_once(prompt)
    except KeyboardInterrupt:
        print()
        continue
    except Exception as exc:
        print("Error:", exc)
        continue