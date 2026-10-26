"""内置工具：getDate（读取本机日期时间）。

保持与原 chat.py 一致的行为：调用系统命令，而非 Python 的日期 API。
"""

from __future__ import annotations

import os
import subprocess

from .base import Tool


class GetDateTool(Tool):
    name = "getDate"
    description = "获取当前电脑本地的日期和时间。"
    parameters = {"type": "object", "properties": {}, "additionalProperties": False}

    def __init__(self, timeout: int = 10) -> None:
        self._timeout = timeout

    def run(self) -> str:
        if os.name == "nt":
            # Windows 的 date /T 只显示日期，time /T 显示时间。
            command = ["cmd", "/c", "date /T & time /T"]
        else:
            # Linux / macOS 的 date 命令本身就会输出日期和时间。
            command = ["date"]

        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=self._timeout,
        )
        output = (result.stdout or "").strip()
        error = (result.stderr or "").strip()
        if result.returncode != 0:
            raise RuntimeError(error or output or "date 命令执行失败")
        if not output:
            raise RuntimeError(error or "date 命令没有输出")
        return output
