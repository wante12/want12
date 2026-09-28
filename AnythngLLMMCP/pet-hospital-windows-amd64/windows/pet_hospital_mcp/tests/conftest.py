from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

import httpx

from pet_hospital_mcp.config import AppSettings
from pet_hospital_mcp.rest_client import PetHospitalRestClient
from pet_hospital_mcp.server import create_app, create_server

PROTOCOL_VERSION = "2026-07-28"
MODERN_META = {
    "io.modelcontextprotocol/protocolVersion": PROTOCOL_VERSION,
    "io.modelcontextprotocol/clientCapabilities": {},
    "io.modelcontextprotocol/clientInfo": {"name": "pytest", "version": "1.0"},
}


@asynccontextmanager
async def running_mcp_app(
    settings: AppSettings,
    backend_handler: Callable[[httpx.Request], httpx.Response],
) -> AsyncIterator[tuple[httpx.AsyncClient, Any, PetHospitalRestClient]]:
    rest_client = PetHospitalRestClient(
        settings,
        transport=httpx.MockTransport(backend_handler),
    )
    server = create_server(settings, rest_client=rest_client)
    app = create_app(server, settings)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            yield client, server, rest_client


async def mcp_request(
    client: httpx.AsyncClient,
    method: str,
    *,
    params: dict[str, Any] | None = None,
    name: str | None = None,
    request_id: int = 1,
) -> httpx.Response:
    body: dict[str, Any] = {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
        "params": {"_meta": MODERN_META, **(params or {})},
    }
    headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "Mcp-Protocol-Version": PROTOCOL_VERSION,
        "Mcp-Method": method,
    }
    if name is not None:
        headers["Mcp-Name"] = name
    return await client.post("/mcp", json=body, headers=headers)


async def call_tool(
    client: httpx.AsyncClient,
    arguments: dict[str, Any],
    *,
    request_id: int = 2,
) -> httpx.Response:
    return await mcp_request(
        client,
        "tools/call",
        params={"name": "list_pets", "arguments": arguments},
        name="list_pets",
        request_id=request_id,
    )
