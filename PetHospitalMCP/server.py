"""宠物医院 MCP 服务 —— 单工具 MVP。

只暴露一个工具 list_pets -> GET /api/v1/pets（过滤 + 排序 + 分页）

传输：Streamable HTTP，无握手、无会话、无长连接。
协议：同时兼容 2026-07-28 之前（旧版 initialize / 无版本头）与之后（单次 POST + _meta 信封）。
     SDK 按 MCP-Protocol-Version 头自动路由到对应处理器。

启动：
    pip install -r requirements.txt
    python server.py                      # 默认 127.0.0.1:8091

环境变量：
    MCP_PORT                默认 8091
    PET_HOSPITAL_BASE_URL   默认 http://127.0.0.1:8080
"""

from __future__ import annotations

import os
from typing import Any, Literal

import httpx
import uvicorn
from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import JSONResponse

BASE_URL = os.environ.get("PET_HOSPITAL_BASE_URL", "http://127.0.0.1:8080").rstrip("/")
PORT = int(os.environ.get("MCP_PORT", "8091"))

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
        async with httpx.AsyncClient(base_url=BASE_URL, timeout=10.0) as c:
            r = await c.get("/api/v1/pets", params=params)
    except httpx.TimeoutException:
        return _err("BACKEND_TIMEOUT", "宠物医院服务端响应超时")
    except httpx.RequestError:
        return _err("BACKEND_UNAVAILABLE", f"无法连接 {BASE_URL}，请先启动 pethospital.exe")

    if r.status_code >= 400:
        return _err("BACKEND_API_ERROR", f"后端返回 HTTP {r.status_code}", {"body": r.text[:300]})
    try:
        body = r.json()
    except ValueError:
        return _err("BACKEND_INVALID_RESPONSE", "后端返回的不是 JSON")
    if body.get("code") not in (None, 200) or "data" not in body:
        return _err("BACKEND_API_ERROR", body.get("message", "后端业务错误"))

    data = body["data"]
    # records/charges 可能是 null，统一成数组，省得客户端再判空
    for it in data.get("items") or []:
        it["records"] = it.get("records") or []
        it["charges"] = it.get("charges") or []
    return data


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
