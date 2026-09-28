"""MCP message middleware enforcing the phase-one tool contract."""

from __future__ import annotations

import logging
import time
from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from mcp import MCPError
from mcp.server.context import CallNext, HandlerResult, ServerRequestContext
from mcp.types import INVALID_REQUEST, CallToolResult
from pydantic import ValidationError

from pet_hospital_mcp import PROTOCOL_VERSION
from pet_hospital_mcp.errors import ErrorCode, PetHospitalError, validation_details
from pet_hospital_mcp.logging_config import log_tool_call
from pet_hospital_mcp.tools.list_pets import ListPetsInput, error_result

logger = logging.getLogger(__name__)


class ModernOnlyMiddleware:
    """Reject legacy initialize/session-era traffic before it reaches handlers."""

    async def __call__(
        self,
        ctx: ServerRequestContext[Any, Any],
        call_next: CallNext,
    ) -> HandlerResult:
        if ctx.method in {"initialize", "notifications/initialized"} or ctx.protocol_version != PROTOCOL_VERSION:
            raise MCPError(
                INVALID_REQUEST,
                f"This server only accepts the stateless {PROTOCOL_VERSION} protocol.",
            )
        return await call_next(ctx)


class ToolCallMiddleware:
    """Validate raw tool arguments before the SDK's permissive argument model."""

    async def __call__(
        self,
        ctx: ServerRequestContext[Any, Any],
        call_next: CallNext,
    ) -> HandlerResult:
        if ctx.method != "tools/call":
            return await call_next(ctx)

        raw_params: Mapping[str, Any] = ctx.params if isinstance(ctx.params, Mapping) else {}
        tool_name = raw_params.get("name")
        displayed_name = tool_name if isinstance(tool_name, str) else "<invalid>"
        arguments = raw_params.get("arguments")
        if arguments is None:
            arguments = {}
        log_params = arguments if isinstance(arguments, Mapping) else {"arguments": arguments}
        start = time.perf_counter()
        status = "SUCCESS"

        try:
            if tool_name != "list_pets":
                status = "VALIDATION_ERROR"
                return error_result(
                    PetHospitalError(
                        ErrorCode.VALIDATION_ERROR,
                        "Unknown tool.",
                        {"tool": displayed_name},
                    )
                )
            if not isinstance(arguments, Mapping):
                status = "VALIDATION_ERROR"
                return error_result(
                    PetHospitalError(
                        ErrorCode.VALIDATION_ERROR,
                        "Invalid list_pets parameters.",
                        {"fields": [{"field": "arguments", "reason": "must be an object"}]},
                    )
                )

            try:
                validated = ListPetsInput.model_validate(dict(arguments))
            except ValidationError as exc:
                status = "VALIDATION_ERROR"
                return error_result(
                    PetHospitalError(
                        ErrorCode.VALIDATION_ERROR,
                        "Invalid list_pets parameters.",
                        validation_details(exc),
                    )
                )

            canonical_params = dict(raw_params)
            canonical_params["name"] = "list_pets"
            canonical_params["arguments"] = validated.model_dump(mode="json", exclude_none=True)
            result = await call_next(replace(ctx, params=canonical_params))
            if isinstance(result, CallToolResult) and result.is_error:
                status = "ERROR"
            return result
        except Exception as exc:
            status = "INTERNAL_ERROR"
            logger.error("Unexpected tools/call failure (%s)", type(exc).__name__)
            return error_result(
                PetHospitalError(
                    ErrorCode.INTERNAL_ERROR,
                    "An internal error occurred while processing the tool call.",
                    {"reason": type(exc).__name__},
                )
            )
        finally:
            log_tool_call(
                logger=logger,
                tool_name=displayed_name,
                params=log_params,
                status=status,
                duration_ms=(time.perf_counter() - start) * 1000,
            )




