"""内置工具：RunCli（调用本地命令行程序）。

流程：
    subprocess 以参数列表执行 command + args（shell=False，不拼接命令字符串）
    收集 stdout / stderr / 退出码，超长输出截断，一并回传给 LLM

设计要点：
- 绝不使用 shell=True：参数作为列表直接传给 exec，避免 shell 注入
- 返回退出码，让模型能判断成功（0）还是失败（非 0）
- 输出超长时保留「开头 + 结尾」，中间标注省略，便于模型同时看到结果与报错尾部
- 所有失败路径都返回可读字符串（由 ToolRegistry 回传给模型），
  不向上抛异常，保证 Agent 循环可以继续

安全说明：
    本工具按需求**不设白名单/黑名单**，命令以运行 Agent 的当前用户权限执行。
    仅适用于受控的教学实验环境。
"""

from __future__ import annotations

import locale
import subprocess
from typing import Any

from ..config import CliSettings
from .base import Tool

# 解码优先级：优先 UTF-8，其次系统本地编码（中文 Windows 通常是 cp936/gbk），
# 最后用 latin-1 兜底（它永不失败，能保留原始字节而不抛异常）
def _fallback_encodings() -> tuple[str, ...]:
    preferred = locale.getpreferredencoding(False) or "utf-8"
    ordered = ["utf-8", preferred, "gbk", "latin-1"]
    seen: list[str] = []
    for enc in ordered:
        if enc.lower() not in {e.lower() for e in seen}:
            seen.append(enc)
    return tuple(seen)


_ENCODINGS = _fallback_encodings()


def _decode(raw: bytes | None) -> str:
    """把子进程输出解码成字符串，兼容中文环境。"""
    if not raw:
        return ""
    for enc in _ENCODINGS:
        try:
            text = raw.decode(enc)
            break
        except (UnicodeDecodeError, LookupError):
            continue
    else:
        text = raw.decode("utf-8", errors="replace")

    # 统一换行符，避免 \r\n 在 Markdown/终端里产生多余空行
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _truncate(text: str, limit: int) -> tuple[str, bool, int]:
    """保留开头与结尾，中间标记省略。

    返回 (处理后的文本, 是否截断, 省略的字符数)。
    保留结尾是因为报错信息常出现在输出末尾。
    """
    if limit <= 0 or len(text) <= limit:
        return text, False, 0

    omitted = len(text) - limit
    head = limit * 2 // 3
    tail = limit - head
    marker = f"\n...（中间省略 {omitted} 字符）...\n"
    return text[:head] + marker + text[-tail:], True, omitted


class RunCliTool(Tool):
    name = "RunCli"
    description = (
        "执行本地已安装的命令行程序（CLI），返回标准输出、标准错误和退出码。"
        "适用于查看目录、读取文件、运行脚本、查询系统信息等需要调用本地程序的场景。"
        "退出码为 0 表示成功，非 0 表示失败（具体原因见 stderr）。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "要执行的程序名或完整路径，如 python、git、dir、ls",
            },
            "args": {
                "type": "array",
                "items": {"type": "string"},
                "description": "传给程序的参数列表，每个参数一个元素，如 [\"-la\", \"/tmp\"]",
            },
        },
        "required": ["command"],
        "additionalProperties": False,
    }

    def __init__(self, settings: CliSettings | None = None) -> None:
        self._settings = settings or CliSettings()

    # ------------------------------------------------------------------ 入口
    def run(self, command: str, args: list[str] | None = None) -> str:
        command = (command or "").strip()
        if not command:
            return "执行失败：command 不能为空。"

        # 参数统一转成字符串；None / 非列表都做容错
        if args is None:
            argv_tail: list[str] = []
        elif isinstance(args, (list, tuple)):
            argv_tail = [str(a) for a in args]
        else:
            return f"执行失败：args 必须是字符串列表，收到的是 {type(args).__name__}。"

        argv = [command, *argv_tail]

        try:
            completed = subprocess.run(
                argv,                      # 参数列表，绝不拼接 shell 字符串
                shell=False,               # 显式关闭 shell
                capture_output=True,       # 捕获 stdout / stderr，不污染 TUI
                timeout=self._settings.timeout,
                cwd=self._settings.workdir or None,
                check=False,               # 非 0 退出码不抛异常，自己处理
            )
        except FileNotFoundError:
            return (
                f"执行失败：找不到程序「{command}」。"
                "请确认该命令已安装并在 PATH 中，或改用完整路径。"
            )
        except PermissionError:
            return f"执行失败：没有权限执行「{command}」。"
        except NotADirectoryError:
            return f"执行失败：工作目录无效（{self._settings.workdir}）。"
        except OSError as exc:
            return f"执行失败：无法启动「{command}」（{exc.strerror or exc}）。"
        except subprocess.TimeoutExpired as exc:
            return self._format_timeout(argv, exc)

        return self._format_result(argv, completed.returncode,
                                   _decode(completed.stdout), _decode(completed.stderr))

    # ------------------------------------------------------------------ 输出
    def _format_timeout(self, argv: list[str], exc: subprocess.TimeoutExpired) -> str:
        """超时也要把已有输出还给模型，便于判断卡在哪一步。"""
        out = _decode(exc.stdout) if exc.stdout else ""
        err = _decode(exc.stderr) if exc.stderr else ""
        lines = [
            f"执行超时：命令在 {self._settings.timeout:.0f} 秒内未结束，已被终止。",
            f"命令：{' '.join(argv)}",
        ]
        if out.strip():
            shown, cut, n = _truncate(out, self._settings.max_output_chars)
            lines += ["", "--- 已捕获的 stdout（可能不完整）---", shown]
            if cut:
                lines.append(f"（已省略 {n} 字符）")
        if err.strip():
            shown, cut, n = _truncate(err, self._settings.max_output_chars)
            lines += ["", "--- 已捕获的 stderr（可能不完整）---", shown]
            if cut:
                lines.append(f"（已省略 {n} 字符）")
        return "\n".join(lines)

    def _format_result(
        self, argv: list[str], exit_code: int, stdout: str, stderr: str
    ) -> str:
        """组织成「命令 / 退出码 / stdout / stderr」的结构化文本。"""
        limit = self._settings.max_output_chars
        lines = [
            f"命令：{' '.join(argv)}",
            f"退出码：{exit_code}" + ("（成功）" if exit_code == 0 else "（失败）"),
        ]

        out_shown, out_cut, out_n = _truncate(stdout.rstrip(), limit)
        err_shown, err_cut, err_n = _truncate(stderr.rstrip(), limit)

        lines += ["", "--- stdout ---", out_shown if out_shown.strip() else "(无输出)"]
        if out_cut:
            lines.append(f"（stdout 过长已截断，省略 {out_n} 字符）")

        # stderr 为空时不必展示，减少噪声
        if err_shown.strip():
            lines += ["", "--- stderr ---", err_shown]
            if err_cut:
                lines.append(f"（stderr 过长已截断，省略 {err_n} 字符）")

        if exit_code != 0 and not err_shown.strip() and not out_shown.strip():
            lines.append("（命令失败但没有任何输出）")

        return "\n".join(lines)
