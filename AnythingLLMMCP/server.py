"""AnythingLLM MCP 服务。

暴露三个工具（均作用于「第一个工作区」）：
    list_workspace_files  读取工作区的文件信息（列表 + 可选内容预览）
    workspace_chat        工作区内的检索增强对话（chat / query 两种模式）
    search_vectors        工作区内向量相似度检索（只检索不生成）

传输：Streamable HTTP，无握手、无会话、无长连接。
协议：同时兼容 2026-07-28 之前（旧版 initialize）与之后（单次 POST + _meta 信封）。

启动：
    pip install -r requirements.txt
    python server.py                      # 默认 127.0.0.1:8093

环境变量：
    MCP_PORT            默认 8093
    ANYTHINGLLM_URL     默认 http://localhost:3001
    ANYTHINGLLM_API_KEY 必填，在 AnythingLLM「设置 → 工具 → 开发者 API」创建
"""

from __future__ import annotations

import os
from typing import Any

import httpx
import uvicorn
from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse

BASE_URL = os.environ.get("ANYTHINGLLM_URL", "http://localhost:3001").rstrip("/")
API_KEY = os.environ.get("ANYTHINGLLM_API_KEY", "").strip()
PORT = int(os.environ.get("MCP_PORT", "8093"))

server = MCPServer(
    name="anythingllm-mcp",
    version="0.1.0",
    instructions="查询 AnythingLLM 第一个工作区的文件信息。只有一个工具 list_workspace_files。",
)


def _headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {API_KEY}", "Accept": "application/json"}


def _err(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": details or {}}}


async def _call(c: httpx.AsyncClient, method: str, path: str, **kw) -> Any:
    """统一请求封装；异常时抛出带 error dict 的 RuntimeError。"""
    try:
        r = await c.request(method, path, headers=_headers(), **kw)
    except httpx.TimeoutException:
        raise RuntimeError(_err("BACKEND_TIMEOUT", "AnythingLLM 响应超时"))
    except httpx.RequestError:
        raise RuntimeError(_err("BACKEND_UNAVAILABLE", f"无法连接 {BASE_URL}，请先启动 AnythingLLM"))

    if r.status_code == 401:
        raise RuntimeError(_err("UNAUTHORIZED", "API Key 无效，请在 AnythingLLM 开发者 API 里重新创建"))
    if r.status_code >= 400:
        raise RuntimeError(_err("BACKEND_API_ERROR", f"HTTP {r.status_code}",
                                {"body": r.text[:300]}))
    try:
        return r.json()
    except ValueError:
        raise RuntimeError(_err("BACKEND_INVALID_RESPONSE", "返回的不是 JSON"))


@server.tool()
async def list_workspace_files(
    preview_chars: int = 0,
    limit: int = 50,
) -> dict[str, Any]:
    """读取 AnythingLLM 第一个工作区的文件信息。

    preview_chars：每个文件返回多少字的内容预览，0 表示不取预览（默认，最省 token）。
    limit：最多返回多少个文件，默认 50。
    """
    if preview_chars < 0:
        return _err("VALIDATION_ERROR", "preview_chars 不能为负")
    if not 1 <= limit <= 200:
        return _err("VALIDATION_ERROR", "limit 必须在 1~200 之间")
    if not API_KEY:
        return _err("CONFIG_ERROR", "未设置 ANYTHINGLLM_API_KEY 环境变量")

    try:
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=20.0) as c:
            # 1) 取工作区列表，拿第一个
            ws = await _call(c, "GET", "/api/v1/workspaces")
            workspaces = ws.get("workspaces") or ws.get("items") or []
            if not workspaces:
                return _err("NO_WORKSPACE", "AnythingLLM 里还没有任何工作区")
            first = workspaces[0]
            slug = first.get("slug") or first.get("id") or first.get("name")

            # 2) 取该工作区的文件信息（返回 { workspace: [ {id,name,slug,documents:[...]} ] }）
            detail = await _call(c, "GET", f"/api/v1/workspace/{slug}")
            ws_obj = (detail.get("workspace") or [{}])[0]
            all_docs = ws_obj.get("documents") or []

            # 3) 可选：逐个取内容预览
            if preview_chars > 0:
                for doc in all_docs[:limit]:
                    loc = doc.get("docpath") or doc.get("location")
                    if not loc:
                        continue
                    try:
                        got = await _call(c, "GET",
                                          f"/api/v1/workspace/{slug}/get-document",
                                          params={"location": loc})
                        doc["contentPreview"] = (got.get("content") or "")[:preview_chars]
                    except RuntimeError:
                        doc["contentPreview"] = ""
    except RuntimeError as e:
        return e.args[0] if e.args else _err("INTERNAL_ERROR", str(e))

    return {
        "workspace": {
            "name": ws_obj.get("name") or first.get("name"),
            "slug": slug,
        },
        "count": len(all_docs),
        "files": [
            {
                # title 可能为空，回退到 docpath 的文件名
                "title": d.get("title") or (d.get("docpath") or "").split("/")[-1],
                "docpath": d.get("docpath"),
                **({"contentPreview": d["contentPreview"]} if "contentPreview" in d else {}),
            }
            for d in all_docs[:limit]
        ],
    }


@server.tool()
async def workspace_chat(
    message: str,
    mode: str = "chat",
    session_id: str = "",
) -> dict[str, Any]:
    """在第一个工作区内进行对话（检索增强问答）。

    message   ：用户问题
    mode      ：chat 为普通对话，query 为只做向量检索不生成（默认 chat）
    session_id：可选，传入则以多轮会话方式提问
    """
    if not (message or "").strip():
        return _err("VALIDATION_ERROR", "message 不能为空")
    if mode not in ("chat", "query"):
        return _err("VALIDATION_ERROR", "mode 只能是 chat 或 query")
    if not API_KEY:
        return _err("CONFIG_ERROR", "未设置 ANYTHINGLLM_API_KEY 环境变量")

    try:
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=60.0) as c:
            slug = await _first_workspace_slug(c)
            if isinstance(slug, dict):
                return slug

            payload: dict[str, Any] = {
                "message": message.strip(),
                "mode": mode,
            }
            if session_id:
                payload["sessionId"] = session_id

            result = await _call(c, "POST", f"/api/v1/workspace/{slug}/chat", json=payload)
    except RuntimeError as e:
        return e.args[0] if e.args else _err("INTERNAL_ERROR", str(e))

    text = result.get("textResponse") or result.get("text") or ""
    sources = result.get("sources") or []
    return {
        "workspace": slug,
        "mode": mode,
        "reply": text,
        "sourceCount": len(sources),
        "sources": [
            {
                "title": s.get("title") or (s.get("url") or "").split("/")[-1],
                "score": round(float(s.get("score") or 0), 4),
            }
            for s in sources[:10]
        ],
    }


@server.tool()
async def search_vectors(
    query: str,
    top_n: int = 4,
    score_threshold: float = 0.2,
) -> dict[str, Any]:
    """在第一个工作区内做向量相似度检索（不生成回答）。

    query：检索语句
    top_n：返回最相关的片段数，默认 4，最大 20
    score_threshold：相似度下限，默认 0.2，低于该值的结果会被过滤
    """
    if not (query or "").strip():
        return _err("VALIDATION_ERROR", "query 不能为空")
    if not 1 <= top_n <= 20:
        return _err("VALIDATION_ERROR", "top_n 必须在 1~20 之间")
    if not 0.0 <= score_threshold <= 1.0:
        return _err("VALIDATION_ERROR", "score_threshold 必须在 0~1 之间")
    if not API_KEY:
        return _err("CONFIG_ERROR", "未设置 ANYTHINGLLM_API_KEY 环境变量")

    try:
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as c:
            slug = await _first_workspace_slug(c)
            if isinstance(slug, dict):
                return slug

            result = await _call(
                c,
                "POST",
                f"/api/v1/workspace/{slug}/vector-search",
                json={
                    "query": query.strip(),
                    "topN": top_n,
                    "scoreThreshold": score_threshold,
                },
            )
    except RuntimeError as e:
        return e.args[0] if e.args else _err("INTERNAL_ERROR", str(e))

    chunks = result.get("results") or []
    return {
        "workspace": slug,
        "query": query.strip(),
        "count": len(chunks),
        "chunks": [
            {
                "title": ch.get("title") or "",
                "score": round(float(ch.get("score") or 0), 4),
                "text": (ch.get("text") or "")[:800],
            }
            for ch in chunks
        ],
    }


async def _first_workspace_slug(c: httpx.AsyncClient):
    """取第一个工作区的 slug。失败时返回 error dict（调用方直接返回）。"""
    try:
        ws = await _call(c, "GET", "/api/v1/workspaces")
    except RuntimeError as e:
        return e.args[0] if e.args else _err("INTERNAL_ERROR", "取工作区失败")
    workspaces = ws.get("workspaces") or ws.get("items") or []
    if not workspaces:
        return _err("NO_WORKSPACE", "AnythingLLM 里还没有任何工作区")
    first = workspaces[0]
    return first.get("slug") or first.get("id") or first.get("name")


@server.custom_route("/health", methods=["GET"])
async def health(_: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "anythingllm": BASE_URL, "hasKey": bool(API_KEY)})


def build_app():
    """无握手/无会话的 Streamable HTTP 应用。"""
    return server.streamable_http_app(
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )


if __name__ == "__main__":
    uvicorn.run(build_app(), host="127.0.0.1", port=PORT, log_level="info")
