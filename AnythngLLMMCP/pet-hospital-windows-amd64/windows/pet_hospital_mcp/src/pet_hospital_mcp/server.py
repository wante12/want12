"""MCPServer assembly and executable entry point."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator

import uvicorn
from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse

from pet_hospital_mcp import PROTOCOL_VERSION, __version__
from pet_hospital_mcp.config import AppSettings
from pet_hospital_mcp.logging_config import configure_logging
from pet_hospital_mcp.middleware import ModernOnlyMiddleware, ToolCallMiddleware
from pet_hospital_mcp.rest_client import PetHospitalRestClient
from pet_hospital_mcp.tools import register_list_pets


def create_server(
    settings: AppSettings | None = None,
    *,
    rest_client: PetHospitalRestClient | None = None,
) -> MCPServer:
    """Build the MCPServer, tool, health route, and lifecycle hooks."""

    settings = settings or AppSettings.from_env()
    configure_logging(settings.log_level)
    client = rest_client or PetHospitalRestClient(settings)

    @asynccontextmanager
    async def lifespan(_: MCPServer) -> AsyncIterator[None]:
        try:
            yield None
        finally:
            await client.aclose()

    server = MCPServer(
        name="pet-hospital-mcp",
        title="Pet Hospital MCP",
        description="Read-only MCP access to the local Pet Hospital REST API.",
        instructions=(
            "Use list_pets to search, filter, sort, and paginate pet hospital records. "
            "This phase exposes no write tools and no second-phase capabilities."
        ),
        version=__version__,
        log_level=settings.log_level,
        lifespan=lifespan,
        middleware=[ModernOnlyMiddleware(), ToolCallMiddleware()],
    )

    @server.custom_route("/health", methods=["GET"])
    async def health_check(_: Request) -> JSONResponse:
        return JSONResponse(
            {
                "status": "healthy",
                "service": "pet-hospital-mcp",
                "version": __version__,
                "protocolVersion": PROTOCOL_VERSION,
                "sdk": "mcp==2.0.0",
            }
        )

    register_list_pets(server, client)
    return server


def create_app(server: MCPServer, settings: AppSettings | None = None) -> Starlette:
    """Create the stateless Streamable HTTP ASGI application."""

    settings = settings or AppSettings.from_env()
    return server.streamable_http_app(
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=True,
        host=settings.host,
        # The teaching scope explicitly excludes Origin and Host validation.
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )


async def _serve() -> None:
    settings = AppSettings.from_env()
    server = create_server(settings)
    app = create_app(server, settings)
    uvicorn_config = uvicorn.Config(
        app,
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
    )
    await uvicorn.Server(uvicorn_config).serve()


def main() -> None:
    asyncio.run(_serve())


if __name__ == "__main__":
    main()

