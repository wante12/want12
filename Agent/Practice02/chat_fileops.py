import configparser
import json
import mimetypes
import os
import shutil
import stat
import subprocess
import sys
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE_DIR)

OPENAI_PATH = r"D:\openai"
if os.path.isdir(OPENAI_PATH):
    sys.path.insert(0, OPENAI_PATH)

from openai import OpenAI

TYPING_DELAY = 0.015
MAX_TOOL_ROUNDS = 12
MAX_TEXT_FILE_CHARS = 100_000
MAX_TOOL_RESULT_DISPLAY = 1_000
CONFIRM_DELETE = True

TEXT_EXTENSIONS = {
    ".txt", ".text", ".md", ".markdown", ".rst",
    ".py", ".pyw", ".js", ".jsx", ".ts", ".tsx",
    ".json", ".jsonl", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf",
    ".csv", ".tsv", ".log", ".xml", ".html", ".htm", ".css", ".scss", ".less",
    ".sql", ".sh", ".bash", ".bat", ".cmd", ".ps1",
    ".c", ".h", ".cpp", ".hpp", ".cc", ".java", ".kt", ".go", ".rs",
    ".php", ".rb", ".pl", ".lua", ".r", ".m", ".swift",
}

TEXT_MIME_TYPES = {
    "application/json",
    "application/ld+json",
    "application/xml",
    "application/xhtml+xml",
    "application/javascript",
    "application/x-javascript",
    "application/x-httpd-php",
    "application/x-sh",
    "application/sql",
    "image/svg+xml",
}

SYSTEM_PROMPT = (
    "你是一个可以调用本地工具的助手。"
    "当用户询问当前日期、时间、今天是几号或现在几点时，"
    "必须调用 getDate 工具获取当前电脑的日期和时间，不要自行猜测。"
    "当用户询问某一年是否为闰年时，必须调用 isLeapYear 工具，"
    "把年份作为 year 参数传入，不要自行判断。"
    "当用户要求查看当前目录、列出目录、查看文件类型、读取、创建、编辑、重命名或删除文件/目录时，"
    "必须调用对应的文件工具，不要假装操作成功。"
    "如果用户没有给出路径，先调用 getCurrentDirectory 获取当前工作目录。"
    "如果操作失败，把工具返回的错误原样告诉用户。"
    "删除操作会要求用户确认。"
)


def make_tool(name, description, properties=None, required=None):
    parameters = {
        "type": "object",
        "properties": properties or {},
        "additionalProperties": False,
    }
    if required:
        parameters["required"] = required

    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": parameters,
        },
    }


TOOLS = [
    make_tool(
        "getDate",
        "获取当前电脑本地的日期和时间。",
    ),
    make_tool(
        "isLeapYear",
        "判断指定年份是否为闰年。",
        {"year": {"type": "integer", "description": "要判断的年份，例如 2024"}},
        ["year"],
    ),
    make_tool(
        "getCurrentDirectory",
        "获取程序当前工作目录的绝对路径。",
    ),
    make_tool(
        "listDirectory",
        "列出指定目录下的所有文件和子目录。",
        {"directory": {"type": "string", "description": "要列出的目录路径。"}},
        ["directory"],
    ),
    make_tool(
        "getFileType",
        "获取指定路径的类型信息，包括文件扩展名和 MIME 类型。",
        {"path": {"type": "string", "description": "要检查的文件或目录路径。"}},
        ["path"],
    ),
    make_tool(
        "readTextFile",
        "读取指定纯文本文件的内容。只支持文本文件，不支持二进制文件。",
        {"path": {"type": "string", "description": "要读取的文本文件路径。"}},
        ["path"],
    ),
    make_tool(
        "createFile",
        "在指定目录下创建一个新的纯文本文件。如果文件已存在则失败。",
        {
            "directory": {"type": "string", "description": "新文件所在的目录。"},
            "filename": {
                "type": "string",
                "description": "新文件名，只能包含文件名，不能包含路径分隔符。",
            },
            "content": {
                "type": "string",
                "description": "文件初始内容，默认为空字符串。",
            },
        },
        ["directory", "filename"],
    ),
    make_tool(
        "editTextFile",
        "编辑指定纯文本文件的内容，可以选择覆盖或追加。",
        {
            "path": {"type": "string", "description": "要编辑的文本文件路径。"},
            "content": {"type": "string", "description": "要写入的文本内容。"},
            "mode": {
                "type": "string",
                "enum": ["overwrite", "append"],
                "description": "overwrite 覆盖原内容；append 追加到末尾。默认 overwrite。",
            },
        },
        ["path", "content"],
    ),
    make_tool(
        "createDirectory",
        "创建一个新目录；如果父目录不存在会自动创建。",
        {"path": {"type": "string", "description": "要创建的目录路径。"}},
        ["path"],
    ),
    make_tool(
        "renamePath",
        "重命名指定的文件或目录，新名称必须在同一目录下。",
        {
            "path": {"type": "string", "description": "要重命名的文件或目录路径。"},
            "new_name": {
                "type": "string",
                "description": "新名称，只能包含名称，不能包含路径分隔符。",
            },
        },
        ["path", "new_name"],
    ),
    make_tool(
        "deleteDirectory",
        "删除指定目录及其所有内容，包括非空目录。执行前会要求用户确认。",
        {"path": {"type": "string", "description": "要删除的目录路径。"}},
        ["path"],
    ),
    make_tool(
        "deleteFile",
        "删除指定文件。执行前会要求用户确认。",
        {"path": {"type": "string", "description": "要删除的文件路径。"}},
        ["path"],
    ),
]


def json_result(data) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2)


def resolve_path(path: str) -> str:
    if not isinstance(path, str) or not path.strip():
        raise ValueError("路径不能为空")
    return os.path.abspath(os.path.expanduser(path.strip()))


def is_text_file(path: str) -> bool:
    try:
        with open(path, "rb") as file:
            sample = file.read(4096)
    except OSError:
        return False

    if b"\x00" in sample:
        return False

    basename = os.path.basename(path).lower()
    if basename in {".gitignore", ".dockerignore", ".env"}:
        return True

    extension = os.path.splitext(path)[1].lower()
    if extension in TEXT_EXTENSIONS:
        return True

    mime_type, _ = mimetypes.guess_type(path)
    if mime_type and mime_type != "application/octet-stream":
        if mime_type.startswith("text/") or mime_type in TEXT_MIME_TYPES:
            return True
        return False

    if not sample:
        return True

    try:
        sample.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def get_date() -> str:
    if os.name == "nt":
        command = ["cmd", "/c", "date /T & time /T"]
    else:
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


def is_leap_year(year: int) -> str:
    year = int(year)
    if year < 1:
        return "年份必须大于 0"

    leap = (year % 4 == 0 and year % 100 != 0) or (year % 400 == 0)
    if leap:
        return f"{year} 年是闰年"
    return f"{year} 年不是闰年"


def get_current_directory() -> str:
    return json_result({"current_directory": os.getcwd()})


def list_directory(directory: str) -> str:
    target = resolve_path(directory)
    if not os.path.isdir(target):
        raise NotADirectoryError(f"目录不存在: {target}")

    entries = []
    with os.scandir(target) as iterator:
        for entry in sorted(iterator, key=lambda item: (not item.is_dir(), item.name.lower())):
            item = {
                "name": entry.name,
                "path": entry.path,
                "type": "directory" if entry.is_dir() else "file",
            }
            if entry.is_file():
                try:
                    item["size"] = entry.stat().st_size
                except OSError:
                    pass
            entries.append(item)

    return json_result({
        "directory": target,
        "count": len(entries),
        "entries": entries,
    })


def get_file_type(path: str) -> str:
    target = resolve_path(path)
    if not os.path.exists(target):
        raise FileNotFoundError(f"路径不存在: {target}")

    if os.path.isdir(target):
        return json_result({"path": target, "type": "directory"})

    extension = os.path.splitext(target)[1].lower()
    mime_type, content_encoding = mimetypes.guess_type(target)

    return json_result({
        "path": target,
        "type": "file",
        "extension": extension or None,
        "mime_type": mime_type or "application/octet-stream",
        "content_encoding": content_encoding,
        "is_text": is_text_file(target),
    })


def detect_text_encoding(path: str) -> str:
    with open(path, "rb") as file:
        raw = file.read(4)

    if raw.startswith(b"\xef\xbb\xbf"):
        try:
            with open(path, "r", encoding="utf-8-sig", errors="strict") as file:
                file.read(4096)
            return "utf-8-sig"
        except UnicodeDecodeError:
            pass

    for encoding in ("utf-8", "gbk"):
        try:
            with open(path, "r", encoding=encoding, errors="strict") as file:
                file.read(4096)
            return encoding
        except UnicodeDecodeError:
            continue

    raise ValueError("无法识别文本编码，只支持 UTF-8 或 GBK 文本文件")


def read_text_file(path: str) -> str:
    target = resolve_path(path)
    if not os.path.isfile(target):
        raise FileNotFoundError(f"文件不存在: {target}")
    if not is_text_file(target):
        raise ValueError("只支持纯文本文件")

    encoding = detect_text_encoding(target)
    with open(target, "r", encoding=encoding, errors="strict") as file:
        content = file.read(MAX_TEXT_FILE_CHARS)
        truncated = bool(file.read(1))

    return json_result({
        "path": target,
        "encoding": encoding,
        "truncated": truncated,
        "content": content,
    })


def create_file(directory: str, filename: str, content: str = "") -> str:
    target_dir = resolve_path(directory)
    if not os.path.isdir(target_dir):
        raise NotADirectoryError(f"目录不存在: {target_dir}")

    if not filename or filename in {".", ".."} or os.path.basename(filename) != filename:
        raise ValueError("filename 只能是不包含路径分隔符的文件名")

    target = os.path.join(target_dir, filename)
    if os.path.exists(target):
        raise FileExistsError(f"文件已存在: {target}")

    if content is None:
        content = ""
    if not isinstance(content, str):
        content = str(content)

    with open(target, "x", encoding="utf-8", newline="") as file:
        file.write(content)

    return json_result({
        "path": target,
        "created": True,
        "characters": len(content),
    })

def edit_text_file(path: str, content: str, mode: str = "overwrite") -> str:
    target = resolve_path(path)
    if not os.path.isfile(target):
        raise FileNotFoundError(f"文件不存在: {target}")
    if not is_text_file(target):
        raise ValueError("只支持纯文本文件")
    if mode not in {"overwrite", "append"}:
        raise ValueError("mode 只能是 overwrite 或 append")

    if content is None:
        content = ""
    if not isinstance(content, str):
        content = str(content)

    encoding = detect_text_encoding(target)
    file_mode = "w" if mode == "overwrite" else "a"
    write_encoding = "utf-8" if mode == "append" and encoding == "utf-8-sig" else encoding
    with open(target, file_mode, encoding=write_encoding, newline="") as file:
        file.write(content)

    return json_result({
        "path": target,
        "mode": mode,
        "encoding": write_encoding,
        "characters_written": len(content),
        "size": os.path.getsize(target),
    })


def create_directory(path: str) -> str:
    target = resolve_path(path)
    if os.path.exists(target):
        raise FileExistsError(f"路径已存在: {target}")

    os.makedirs(target, exist_ok=False)
    return json_result({"path": target, "created": True})


def rename_path(path: str, new_name: str) -> str:
    """重命名文件或目录，新名称必须在同一目录下。"""
    target = resolve_path(path)
    if not os.path.lexists(target):
        raise FileNotFoundError(f"路径不存在: {target}")

    if not new_name or new_name in {".", ".."} or os.path.basename(new_name) != new_name:
        raise ValueError("new_name 只能是不包含路径分隔符的名称")

    if target in {
        os.path.abspath(__file__),
        os.path.abspath(os.path.join(BASE_DIR, "config.ini")),
    }:
        raise PermissionError("不能重命名程序运行所需的文件")

    if os.path.ismount(target):
        raise PermissionError("不能重命名挂载点或磁盘根目录")

    cwd = os.path.abspath(os.getcwd())
    try:
        if os.path.commonpath([target, cwd]) == target:
            raise PermissionError("不能重命名当前工作目录或其父目录")
    except ValueError:
        pass

    new_path = os.path.join(os.path.dirname(target), new_name)
    same_entry = os.path.normcase(new_path) == os.path.normcase(target)
    if not same_entry and os.path.exists(new_path):
        raise FileExistsError(f"目标名称已存在: {new_path}")

    if new_path == target:
        return json_result({
            "path": target,
            "new_path": new_path,
            "renamed": False,
            "reason": "名称相同",
        })

    os.rename(target, new_path)
    return json_result({
        "path": target,
        "new_path": new_path,
        "renamed": True,
    })


def ensure_safe_delete_target(target: str) -> None:
    cwd = os.path.abspath(os.getcwd())
    home = os.path.abspath(os.path.expanduser("~"))
    _, tail = os.path.splitdrive(target)

    if target == os.path.abspath(os.sep):
        raise PermissionError("不能删除文件系统根目录")
    if tail in ("\\", "/"):
        raise PermissionError("不能删除磁盘根目录")
    if os.path.ismount(target):
        raise PermissionError("不能删除挂载点或磁盘根目录")
    if target == home:
        raise PermissionError("不能删除用户主目录")
    if target == BASE_DIR:
        raise PermissionError("不能删除程序所在目录")
    if target in {
        os.path.abspath(__file__),
        os.path.abspath(os.path.join(BASE_DIR, "config.ini")),
    }:
        raise PermissionError("不能删除程序运行所需的文件")

    try:
        if os.path.commonpath([target, cwd]) == target:
            raise PermissionError("不能删除当前工作目录或其父目录")
    except ValueError:
        pass


def confirm_delete(action: str, target: str) -> bool:
    if not CONFIRM_DELETE:
        return True

    try:
        answer = input(f"确认{action} {target} ? [y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False

    return answer in {"y", "yes"}


def delete_directory(path: str) -> str:
    target = resolve_path(path)
    if not os.path.isdir(target):
        raise NotADirectoryError(f"目录不存在: {target}")
    if os.path.islink(target) or (hasattr(os.path, "isjunction") and os.path.isjunction(target)):
        raise PermissionError("不允许删除符号链接或目录联接")

    ensure_safe_delete_target(target)
    if not confirm_delete("删除目录", target):
        return json_result({"path": target, "deleted": False, "reason": "用户取消"})

    def remove_readonly(func, current_path, exc_info):
        os.chmod(current_path, stat.S_IWRITE)
        func(current_path)

    if sys.version_info >= (3, 12):
        shutil.rmtree(target, onexc=remove_readonly)
    else:
        shutil.rmtree(target, onerror=remove_readonly)
    return json_result({"path": target, "deleted": True})


def delete_file(path: str) -> str:
    target = resolve_path(path)
    if os.path.isdir(target):
        raise IsADirectoryError(f"这是目录，请使用 deleteDirectory: {target}")
    if not os.path.isfile(target):
        raise FileNotFoundError(f"文件不存在: {target}")

    ensure_safe_delete_target(target)
    if not confirm_delete("删除文件", target):
        return json_result({"path": target, "deleted": False, "reason": "用户取消"})

    try:
        os.remove(target)
    except PermissionError:
        os.chmod(target, stat.S_IWRITE)
        os.remove(target)

    return json_result({"path": target, "deleted": True})


TOOL_HANDLERS = {
    "getDate": get_date,
    "isLeapYear": is_leap_year,
    "getCurrentDirectory": get_current_directory,
    "listDirectory": list_directory,
    "getFileType": get_file_type,
    "readTextFile": read_text_file,
    "createFile": create_file,
    "editTextFile": edit_text_file,
    "createDirectory": create_directory,
    "renamePath": rename_path,
    "deleteDirectory": delete_directory,
    "deleteFile": delete_file,
}


def execute_tool_call(tool_call: dict) -> str:
    name = tool_call.get("function", {}).get("name", "")
    arguments_text = tool_call.get("function", {}).get("arguments") or "{}"

    try:
        arguments = json.loads(arguments_text)
    except json.JSONDecodeError as exc:
        return f"工具参数解析失败: {exc}"

    if not isinstance(arguments, dict):
        return "工具参数必须是 JSON 对象"

    handler = TOOL_HANDLERS.get(name)
    if handler is None:
        return f"未知工具: {name}"

    try:
        return str(handler(**arguments))
    except Exception as exc:
        return f"工具 {name} 执行失败: {exc}"


def stream_completion(messages):
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
            for char in piece:
                print(char, end="", flush=True)
                time.sleep(TYPING_DELAY)

        for tool_call in delta.tool_calls or []:
            index = tool_call.index if tool_call.index is not None else 0
            entry = tool_calls.setdefault(
                index,
                {
                    "id": "",
                    "type": "function",
                    "function": {"name": "", "arguments": ""},
                },
            )

            if tool_call.id:
                entry["id"] = tool_call.id
            if tool_call.type:
                entry["type"] = tool_call.type

            function = tool_call.function
            if function:
                if function.name:
                    entry["function"]["name"] += function.name
                if function.arguments:
                    entry["function"]["arguments"] += function.arguments

    return "".join(content_parts), [tool_calls[index] for index in sorted(tool_calls)]


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

                    preview = result
                    if len(preview) > MAX_TOOL_RESULT_DISPLAY:
                        preview = preview[:MAX_TOOL_RESULT_DISPLAY] + "..."
                    print(f"[工具返回] {preview}")

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
        del messages[start_len:]
        raise


def main() -> None:
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


if __name__ == "__main__":
    main()