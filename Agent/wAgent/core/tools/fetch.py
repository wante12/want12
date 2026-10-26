"""内置工具：fetchWeb（获取网页正文）。

流程：
    1. subprocess 调用本地 curl 取 HTML（参数列表执行，不使用 shell=True）
    2. trafilatura 提取正文并转 Markdown
    3. 返回「URL + 正文 Markdown」给 LLM

设计要点：
- 用 trafilatura 自动去除导航栏 / 广告 / 页脚，只留正文
- 保留标题、段落、列表、表格与链接
- 所有失败路径都返回可读字符串（由 ToolRegistry 回传给模型），
  不向上抛异常，保证 Agent 循环可以继续
"""

from __future__ import annotations

import subprocess
from typing import Any

from ..config import FetchSettings
from .base import Tool

# 允许 curl 跟随的重定向次数上限
_MAX_REDIRECTS = 5

# curl -w 追加的状态码分隔标记（正文里几乎不可能出现）
_STATUS_MARKER = "\n__FETCHWEB_STATUS__:"


class FetchWebTool(Tool):
    name = "fetchWeb"
    description = (
        "获取指定网页的正文内容（已清理导航、广告、页脚，保留标题/段落/列表/表格/链接）。"
        "当需要阅读某篇文章全文，或在 searchWeb 得到链接后想深入了解具体内容时使用。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "要抓取的网页地址，必须以 http:// 或 https:// 开头",
            }
        },
        "required": ["url"],
        "additionalProperties": False,
    }

    def __init__(self, settings: FetchSettings | None = None) -> None:
        self._settings = settings or FetchSettings()

    # ------------------------------------------------------------------ 入口
    def run(self, url: str) -> str:
        url = (url or "").strip()
        if not url:
            return "抓取失败：url 不能为空。"

        if not url.lower().startswith(("http://", "https://")):
            return f"抓取失败：url 必须是以 http:// 或 https:// 开头的完整地址，收到的是「{url}」。"

        try:
            html, _status = self._download(url)
        except _FetchError as exc:
            return f"抓取失败：{exc.reason}"
        except Exception as exc:  # noqa: BLE001 兜底，避免中断对话
            return f"抓取失败：未预期的错误（{type(exc).__name__}: {exc}）"

        return self._extract(url, html)

    # ------------------------------------------------------------------ 下载
    def _download(self, url: str) -> tuple[str, int]:
        """用 curl 取回 (HTML, HTTP状态码)。参数列表方式，不经 shell。"""
        # -sS 静默但保留错误；-L 跟随重定向；--max-time 总超时；
        # --compressed 让服务端压缩、curl 自动解压（省流量）；
        # -w 在响应体后追加状态码，用于识别 4xx/5xx（含返回 200 的软 404 之外的硬错误）
        argv = [
            self._settings.curl_path,
            "-sS",
            "-L",
            "--max-time",
            str(int(self._settings.timeout)),
            "--max-redirs",
            str(_MAX_REDIRECTS),
            "--compressed",
            "-A",
            self._settings.user_agent,
            # 明确要求 HTML，避免服务端返回 JSON/二进制
            "-H",
            "Accept: text/html,application/xhtml+xml",
            "-w",
            _STATUS_MARKER + "%{http_code}",
            url,
        ]

        try:
            result = subprocess.run(
                argv,                       # 参数列表，绝不拼字符串
                capture_output=True,
                timeout=self._settings.timeout + 5,
                check=False,
            )
        except FileNotFoundError as exc:
            raise _FetchError(
                f"找不到 curl 程序（{self._settings.curl_path}）。"
                "请确认系统已安装 curl，或在 config.ini 的 [fetch] 段用 curl_path 指定完整路径。"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise _FetchError(
                f"请求超时（超过 {self._settings.timeout:.0f} 秒），请稍后重试或更换网址。"
            ) from exc

        stderr = result.stderr.decode("utf-8", errors="replace").strip()
        if result.returncode != 0:
            raise _FetchError(self._describe_curl_error(result.returncode, stderr))

        raw = result.stdout.decode("utf-8", errors="replace")
        html, status = self._split_status(raw)

        if status and status >= 400:
            raise _FetchError(
                f"网页返回 HTTP {status}（{'未找到，请检查网址' if status == 404 else '访问被拒绝或服务器错误'}）。"
            )

        if not html.strip():
            raise _FetchError("网页返回内容为空。")
        return html, status

    @staticmethod
    def _split_status(raw: str) -> tuple[str, int]:
        """拆开 -w 追加的状态码。"""
        idx = raw.rfind(_STATUS_MARKER)
        if idx < 0:
            return raw, 0
        html, status_text = raw[:idx], raw[idx + len(_STATUS_MARKER):].strip()
        try:
            return html, int(status_text)
        except ValueError:
            return html, 0

    @staticmethod
    def _describe_curl_error(code: int, stderr: str) -> str:
        """把 curl 退出码翻译成可读原因。"""
        hint = {
            1: "不支持的协议（url 格式可能有误）",
            3: "网址格式错误",
            6: "无法解析域名，请检查网址是否正确或网络是否正常",
            7: "无法连接到服务器（连接被拒绝或网络不通）",
            22: "服务器返回错误状态码（如 404/403）",
            28: "请求超时",
            35: "SSL/TLS 握手失败",
            47: "重定向次数过多",
            52: "服务器返回空响应",
            56: "接收数据失败（连接被重置）",
            60: "SSL 证书校验失败",
        }.get(code, "网页访问失败")

        detail = f"（{stderr[:160]}）" if stderr else ""
        return f"{hint}，curl 退出码 {code}{detail}"

    # ------------------------------------------------------------------ 提取
    def _extract(self, url: str, html: str) -> str:
        """用 trafilatura 抽取正文并转 Markdown。"""
        try:
            import trafilatura
        except ImportError:
            return "抓取失败：缺少 trafilatura 库，请执行 pip install trafilatura。"

        try:
            markdown = trafilatura.extract(
                html,
                url=url,
                output_format="markdown",
                include_links=True,      # 保留链接
                include_tables=True,     # 保留表格
                include_formatting=True, # 保留标题层级
                include_comments=False,  # 去掉评论区
                favor_recall=True,       # 宁可多留正文，少漏内容
            )
        except Exception as exc:  # noqa: BLE001 trafilatura 内部异常类型不固定
            return f"抓取失败：HTML 解析出错（{type(exc).__name__}: {exc}）。该网页可能不是标准 HTML。"

        if not markdown or not markdown.strip():
            return (
                f"抓取失败：已成功下载网页，但无法从中提取正文。"
                f"该页面可能是纯 JS 渲染、需要登录，或内容形式不是文章（如首页/列表页）。网址：{url}"
            )

        text = markdown.strip()
        truncated = False
        if len(text) > self._settings.max_chars:
            text = text[: self._settings.max_chars]
            # 尽量在段落边界截断，避免切断句子
            cut = text.rfind("\n\n")
            if cut > self._settings.max_chars * 0.6:
                text = text[:cut]
            truncated = True

        header = f"网页正文（来源：{url}）："
        footer = (
            f"\n\n（正文较长，已截断，仅保留前 {len(text)} 字符）" if truncated else ""
        )
        return f"{header}\n\n{text}{footer}"


class _FetchError(Exception):
    """内部使用：携带已翻译好的错误原因。"""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason
