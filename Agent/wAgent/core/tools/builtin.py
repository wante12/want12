"""内置工具：getDate（读取本机日期时间）、isLeapYear（闰年判定）。

getDate 保持与原 chat.py 一致的行为：调用系统命令，而非 Python 的日期 API。
isLeapYear 沿用 Practice02 的判定规则，现已并入 wAgent 工具集。
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


class IsLeapYearTool(Tool):
    """判断给定年份是否为闰年。

    判定规则：能被 4 整除且不能被 100 整除，或能被 400 整除。
    """

    name = "isLeapYear"
    description = (
        "判断某个年份是否为闰年。用户询问闰年、平年、二月天数，"
        "或需要按年份推算日期时使用。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "year": {
                "type": "integer",
                "description": "要判断的年份，例如 2024",
            },
        },
        "required": ["year"],
        "additionalProperties": False,
    }

    def run(self, year: int) -> str:
        try:
            year = int(year)
        except (TypeError, ValueError):
            return f"判断失败：year 必须是整数，收到「{year}」。"

        if year < 1:
            return "判断失败：年份必须大于 0。"

        leap = (year % 4 == 0 and year % 100 != 0) or (year % 400 == 0)
        days = 366 if leap else 365
        feb = 29 if leap else 28
        if leap:
            return f"{year} 年是闰年（全年 {days} 天，二月 {feb} 天）"
        return f"{year} 年不是闰年（全年 {days} 天，二月 {feb} 天）"


__all__ = ["GetDateTool", "IsLeapYearTool"]
