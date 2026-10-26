"""内置工具：searchWeb（联网搜索）。

调用百度千帆「智能搜索生成」API，把搜索结果整理成
「摘要 + 参考来源（标题/URL）」返回给 LLM。

设计要点：
- API Key 从 SearchSettings 注入，不在代码中硬编码
- 所有失败路径都返回可读字符串（由 ToolRegistry 回传给模型），
  不向上抛异常，保证 Agent 循环可以继续
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from ..config import SearchSettings
from .base import Tool

# 单个来源摘要的最大长度，避免撑爆上下文
_SNIPPET_LIMIT = 400


class SearchWebTool(Tool):
    name = "searchWeb"
    description = (
        "联网搜索互联网上的最新信息。当用户询问时事、新闻、近期动态，"
        "或需要模型知识库之外的最新信息时使用。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "搜索关键词或一个自然语言问题",
            }
        },
        "required": ["query"],
        "additionalProperties": False,
    }

    def __init__(self, settings: SearchSettings) -> None:
        self._settings = settings

    # ------------------------------------------------------------------ 入口
    def run(self, query: str) -> str:
        query = (query or "").strip()
        if not query:
            return "搜索失败：query 不能为空。"

        if not self._settings.configured:
            return (
                "搜索功能未配置：config.ini 的 [search] 段缺少 baidu_qianfan_api_key。"
                "请在 https://console.bce.baidu.com/ 创建 API Key 后填入配置。"
            )

        try:
            payload = self._request(query)
        except _SearchError as exc:
            return f"搜索失败：{exc.reason}"
        except Exception as exc:  # noqa: BLE001 兜底，避免中断对话
            return f"搜索失败：未预期的错误（{type(exc).__name__}: {exc}）"

        return self._format(query, payload)

    # ------------------------------------------------------------------ HTTP
    def _request(self, query: str) -> dict[str, Any]:
        body = {
            "messages": [{"role": "user", "content": query}],
            "stream": False,
            "resource_id": self._settings.resource_id,
            "search_source": self._settings.search_source,
        }
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            self._settings.endpoint,
            data=data,
            method="POST",
            headers={
                "Authorization": f"Bearer {self._settings.api_key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )

        try:
            with urllib.request.urlopen(req, timeout=self._settings.timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            raise _SearchError(self._describe_http_error(exc)) from exc
        except urllib.error.URLError as exc:
            raise _SearchError(f"网络连接失败（{exc.reason}），请检查网络或代理设置。") from exc
        except TimeoutError as exc:
            raise _SearchError(
                f"请求超时（超过 {self._settings.timeout:.0f} 秒），请稍后重试。"
            ) from exc

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise _SearchError(f"接口返回的不是合法 JSON：{raw[:120]}") from exc

        if isinstance(payload, dict) and payload.get("code") not in (None, 0, "0"):
            raise _SearchError(
                f"接口业务错误 code={payload.get('code')}: "
                f"{payload.get('message') or payload.get('error_msg') or '无详细信息'}"
            )
        if not isinstance(payload, dict):
            raise _SearchError("接口返回结构异常（不是 JSON 对象）。")

        return payload

    @staticmethod
    def _describe_http_error(exc: urllib.error.HTTPError) -> str:
        """把 HTTP 错误翻译成对模型/用户友好的话术。"""
        hint = {
            400: "请求参数有误（检查 query 或配置项）",
            401: "API Key 无效或已失效，请到千帆控制台重新创建后更新 config.ini",
            403: "无权访问该服务（Key 缺少权限或服务未开通）",
            429: "请求过于频繁或超出配额，请稍后重试",
            500: "服务端内部错误，请稍后重试",
            503: "服务暂时不可用，请稍后重试",
        }.get(exc.code, "接口调用失败")

        detail = ""
        try:
            body = exc.read().decode("utf-8", errors="replace")
            parsed = json.loads(body)
            if isinstance(parsed, dict):
                detail = str(parsed.get("message") or parsed.get("error_msg") or "")[:200]
            else:
                detail = body[:200]
        except Exception:  # noqa: BLE001 读错误体失败不影响主流程
            pass

        return f"HTTP {exc.code} {hint}" + (f"（详情：{detail}）" if detail else "")

    # ------------------------------------------------------------------ 整理
    def _format(self, query: str, payload: dict[str, Any]) -> str:
        """把接口结果整理成「摘要 + 参考来源」的文本。"""
        references = payload.get("references") or payload.get("search_results") or []
        if not isinstance(references, list) or not references:
            return f'未找到与「{query}」相关的搜索结果。'

        rows = [r for r in references if isinstance(r, dict)][: self._settings.top_k]
        if not rows:
            return f'未找到与「{query}」相关的搜索结果。'

        # 摘要在最前面：模型优先看到结论性内容
        lines: list[str] = [f"关于「{query}」的搜索结果：", ""]

        for idx, ref in enumerate(rows, start=1):
            snippet = (ref.get("snippet") or ref.get("content") or ref.get("summary") or "").strip()
            snippet = " ".join(snippet.split())  # 压缩空白
            if len(snippet) > _SNIPPET_LIMIT:
                snippet = snippet[:_SNIPPET_LIMIT] + "…"
            title = (ref.get("title") or ref.get("website") or "(无标题)").strip()
            site = (ref.get("website") or "").strip()
            date = (ref.get("date") or "").strip()

            meta = " · ".join(x for x in (site, date) if x)
            lines.append(f"[{idx}] {title}" + (f"（{meta}）" if meta else ""))
            if snippet:
                lines.append(snippet)
            lines.append("")

        lines.append("参考来源：")
        for idx, ref in enumerate(rows, start=1):
            title = (ref.get("title") or "(无标题)").strip()
            url = (ref.get("url") or "").strip()
            if url:
                lines.append(f"[{idx}] {title} - {url}")

        return "\n".join(lines).strip()


class _SearchError(Exception):
    """内部使用：携带已翻译好的错误原因。"""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason
