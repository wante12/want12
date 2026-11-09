"""宠物医院 MCP 服务 —— 单工具 MVP。

只暴露一个工具 list_pets -> GET /api/v1/pets（过滤 + 排序 + 分页）

传输：Streamable HTTP，无握手、无会话、无长连接。
协议：同时兼容 2026-07-28 之前（旧版 initialize / 无版本头）与之后（单次 POST + _meta 信封）。
     SDK 按 MCP-Protocol-Version 头自动路由到对应处理器。

启动：
    pip install -r requirements.txt
    python server.py                      # 默认 127.0.0.1:8090

环境变量：
    MCP_PORT                默认 8090
    PET_HOSPITAL_BASE_URL   默认 http://127.0.0.1:8080
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from datetime import datetime
from typing import Any, Literal

import httpx
import uvicorn
from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse

BASE_URL = os.environ.get("PET_HOSPITAL_BASE_URL", "http://127.0.0.1:8080").rstrip("/")
PORT = int(os.environ.get("MCP_PORT", "8090"))
#: 后端请求的重试次数（含首次），可用环境变量调整
try:
    MAX_RETRIES = max(1, int(os.environ.get("PET_HOSPITAL_RETRIES", "3")))
except ValueError:
    MAX_RETRIES = 3

SPECIES = ("犬", "猫", "兔", "鸟", "仓鼠", "爬宠", "其他")
STATUS = ("待就诊", "就诊中", "住院中", "已康复", "慢性病随访")
SORT_FIELDS = ("id", "name", "ownerName", "species", "doctor", "disease",
               "status", "totalCost", "visitCount", "createdAt", "updatedAt")

server = MCPServer(
    name="pet-hospital-mcp",
    version="0.1.0",
    instructions="宠物医院数据查询。只有一个工具 list_pets。",
)


@server.tool()
async def list_pets(
    q: str | None = None,
    name: str | None = None,
    ownerName: str | None = None,
    ownerPhone: str | None = None,
    species: Literal[SPECIES] | None = None,
    doctor: str | None = None,
    disease: str | None = None,
    status: Literal[STATUS] | None = None,
    min: float | None = None,
    max: float | None = None,
    sortBy: Literal[SORT_FIELDS] | None = None,
    order: Literal["asc", "desc"] | None = None,
    page: int = 1,
    pageSize: int = 20,
) -> dict[str, Any]:
    """查询宠物列表，支持过滤、排序、分页，返回宠物档案、病历与消费明细。

    参数均为可选：q 关键词模糊搜索；name/ownerName/ownerPhone 按名字或主人；
    species 种类；doctor 医生；disease 疾病；status 就诊状态；
    min/max 总花费区间；sortBy 排序字段 + order 方向；page 从 1 开始，pageSize 1~500。
    """
    # 后端对非法值一律返回空列表，所以校验必须在这里做
    if page < 1:
        return _err("VALIDATION_ERROR", "page 必须 >= 1")
    if not 1 <= pageSize <= 500:
        return _err("VALIDATION_ERROR", "pageSize 必须在 1~500 之间")
    if min is not None and max is not None and min > max:
        return _err("VALIDATION_ERROR", "min 不能大于 max")
    if min is not None and min < 0 or max is not None and max < 0:
        return _err("VALIDATION_ERROR", "min/max 不能为负")

    params = {k: v for k, v in {
        "q": q, "name": name, "ownerName": ownerName, "ownerPhone": ownerPhone,
        "species": species, "doctor": doctor, "disease": disease, "status": status,
        "min": min, "max": max, "sortBy": sortBy, "order": order,
        "page": page, "pageSize": pageSize,
    }.items() if v is not None}

    try:
        status_code, body = await _request_with_retry(
            "GET", "/api/v1/pets", tool="list_pets", params=params
        )
    except RuntimeError as exc:
        return exc.args[0] if exc.args else _err("INTERNAL_ERROR", str(exc))

    if status_code >= 400:
        return _err(
            "BACKEND_API_ERROR",
            f"后端返回 HTTP {status_code}",
            {"body": (body if isinstance(body, str) else str(body))[:300]},
        )
    if not isinstance(body, dict):
        return _err("BACKEND_INVALID_RESPONSE", "后端返回的不是 JSON")
    if body.get("code") not in (None, 200) or "data" not in body:
        return _err("BACKEND_API_ERROR", body.get("message", "后端业务错误"))

    data = body["data"]
    # records/charges 可能是 null，统一成数组，省得客户端再判空
    for it in data.get("items") or []:
        it["records"] = it.get("records") or []
        it["charges"] = it.get("charges") or []
    return data


# ====================================================================== 请求封装
#: 可重试的状态码（服务端临时故障）
RETRYABLE_STATUS = {429, 500, 502, 503, 504}
#: 退避基数（秒）
BACKOFF_BASE = 0.4


def _log(event: str, **fields: Any) -> None:
    """结构化日志：每行一条 JSON，便于采集与检索。"""
    record = {
        "ts": datetime.now().isoformat(timespec="milliseconds"),
        "event": event,
        **fields,
    }
    print(json.dumps(record, ensure_ascii=False), file=sys.stderr, flush=True)


async def _request_with_retry(
    method: str,
    path: str,
    *,
    tool: str,
    params: dict | None = None,
    json_body: dict | None = None,
) -> tuple[int, Any]:
    """带重试与结构化日志的 HTTP 请求。

    返回 (status_code, body)。body 为解析后的 JSON 或原始文本。
    连接失败 / 超时 / 可重试状态码都会重试；最终仍失败则抛 RuntimeError(err_dict)。
    """
    started = time.perf_counter()
    last_error = ""

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            async with httpx.AsyncClient(base_url=BASE_URL, timeout=10.0) as c:
                r = await c.request(method, path, params=params, json=json_body)
            elapsed = round((time.perf_counter() - started) * 1000, 1)

            if r.status_code in RETRYABLE_STATUS and attempt < MAX_RETRIES:
                last_error = f"HTTP {r.status_code}"
                _log("backend_retry", tool=tool, path=path, attempt=attempt,
                     status=r.status_code, elapsed_ms=elapsed, reason=last_error)
                await asyncio.sleep(BACKOFF_BASE * (2 ** (attempt - 1)))
                continue

            try:
                body = r.json()
            except ValueError:
                body = r.text

            _log(
                "backend_ok" if r.status_code < 400 else "backend_error",
                tool=tool, path=path, attempt=attempt,
                status=r.status_code, elapsed_ms=elapsed,
            )
            return r.status_code, body

        except httpx.TimeoutException:
            last_error = "timeout"
            _log("backend_retry", tool=tool, path=path, attempt=attempt,
                 elapsed_ms=round((time.perf_counter() - started) * 1000, 1),
                 reason=last_error)
        except httpx.RequestError as exc:
            last_error = type(exc).__name__
            _log("backend_retry", tool=tool, path=path, attempt=attempt,
                 elapsed_ms=round((time.perf_counter() - started) * 1000, 1),
                 reason=last_error)

        if attempt < MAX_RETRIES:
            await asyncio.sleep(BACKOFF_BASE * (2 ** (attempt - 1)))

    elapsed = round((time.perf_counter() - started) * 1000, 1)
    _log("backend_failed", tool=tool, path=path, attempts=MAX_RETRIES,
         elapsed_ms=elapsed, reason=last_error)

    if last_error == "timeout":
        raise RuntimeError(
            _err("BACKEND_TIMEOUT", f"宠物医院服务端响应超时（已重试 {MAX_RETRIES} 次）")
        )
    raise RuntimeError(
        _err(
            "BACKEND_UNAVAILABLE",
            f"无法连接 {BASE_URL}（已重试 {MAX_RETRIES} 次），请先启动 pethospital.exe",
            {"lastError": last_error},
        )
    )


def _err(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": details or {}}}


@server.custom_route("/health", methods=["GET"])
async def health(_: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "backend": BASE_URL})


def build_app():
    """无握手/无会话的 Streamable HTTP 应用。

    stateless_http=True：每个请求独立处理，不建会话、不发 Mcp-Session-Id、不用长连接。
    """
    return server.streamable_http_app(
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )


if __name__ == "__main__":
    uvicorn.run(build_app(), host="127.0.0.1", port=PORT, log_level="info")
