"""The single phase-one MCP tool: `list_pets`."""

from __future__ import annotations

import json
import logging
from typing import Annotated, Literal

from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from mcp.types import CallToolResult, TextContent, ToolAnnotations
from pydantic import BaseModel, ConfigDict, Field, model_validator

from pet_hospital_mcp.errors import (
    ErrorCode,
    ErrorEnvelope,
    ErrorInfo,
    PetHospitalError,
    validation_details,
)
from pet_hospital_mcp.rest_client import ListPetsOutput, PetHospitalRestClient

logger = logging.getLogger(__name__)

Species = Literal["犬", "猫", "兔", "鸟", "仓鼠", "爬宠", "其他"]
Status = Literal["待就诊", "就诊中", "住院中", "已康复", "慢性病随访"]
SortBy = Literal[
    "id",
    "name",
    "ownerName",
    "species",
    "doctor",
    "disease",
    "status",
    "totalCost",
    "visitCount",
    "createdAt",
    "updatedAt",
]
Order = Literal["asc", "desc"]

TOOL_DESCRIPTION = """\
查询宠物医院档案列表，严格转发到现有 Go API 的 GET /api/v1/pets。

适用场景：按宠物、主人、医生、疾病、种类或就诊状态检索档案；按总花费区间筛选；
排序和分页浏览；查看每条档案的总花费、就诊次数、历史病历和消费明细。

支持且仅支持这些参数：q、name、ownerName、ownerPhone、species、doctor、disease、
status、min、max、sortBy、order、page、pageSize。未知参数会被拒绝。

返回值对应 Go API 成功响应的 data：items、total、page、pageSize、totalPages、
totalCost。items 中的 records 和 charges 可能是 null 或数组。失败时返回统一结构：
{"error": {"code": "...", "message": "...", "details": {}}}。
"""


class ListPetsInput(BaseModel):
    """Strict input model for all supported backend query parameters."""

    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

    q: str | None = None
    name: str | None = None
    ownerName: str | None = None
    ownerPhone: str | None = None
    species: Species | None = None
    doctor: str | None = None
    disease: str | None = None
    status: Status | None = None
    min: float | None = Field(default=None, ge=0)
    max: float | None = Field(default=None, ge=0)
    sortBy: SortBy | None = None
    order: Order | None = None
    page: int = Field(default=1, ge=1)
    pageSize: int = Field(default=20, ge=1, le=500)

    @model_validator(mode="after")
    def validate_cost_range(self) -> "ListPetsInput":
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError("min must be less than or equal to max")
        return self


ToolResult = CallToolResult
ToolContext = Context




def success_result(output: ListPetsOutput) -> CallToolResult:
    structured = output.model_dump(mode="json", exclude_unset=True)
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(structured, ensure_ascii=False))],
        structured_content=structured,
    )


def error_result(error: PetHospitalError | ErrorInfo) -> CallToolResult:
    info = error if isinstance(error, ErrorInfo) else ErrorInfo(
        code=error.code,
        message=error.message,
        details=error.details,
    )
    structured = ErrorEnvelope(error=info).model_dump(mode="json")
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(structured, ensure_ascii=False))],
        structured_content=structured,
        is_error=True,
    )


def register_list_pets(server: MCPServer, client: PetHospitalRestClient) -> None:
    """Register `list_pets` and expose all 14 backend query fields flat in the schema."""

    @server.tool(
        name="list_pets",
        title="List pet hospital records",
        description=TOOL_DESCRIPTION,
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
    )
    async def list_pets(
        ctx: ToolContext,
        q: str | None = None,
        name: str | None = None,
        ownerName: str | None = None,
        ownerPhone: str | None = None,
        species: Species | None = None,
        doctor: str | None = None,
        disease: str | None = None,
        status: Status | None = None,
        min: Annotated[float | None, Field(ge=0)] = None,
        max: Annotated[float | None, Field(ge=0)] = None,
        sortBy: SortBy | None = None,
        order: Order | None = None,
        page: Annotated[int, Field(ge=1)] = 1,
        pageSize: Annotated[int, Field(ge=1, le=500)] = 20,
    ) -> ToolResult:
        del ctx  # The rest client is closed through the server lifespan.
        try:
            filters = ListPetsInput(
                q=q,
                name=name,
                ownerName=ownerName,
                ownerPhone=ownerPhone,
                species=species,
                doctor=doctor,
                disease=disease,
                status=status,
                min=min,
                max=max,
                sortBy=sortBy,
                order=order,
                page=page,
                pageSize=pageSize,
            )
        except Exception as exc:  # Defensive path for direct, non-HTTP callers.
            from pydantic import ValidationError

            if isinstance(exc, ValidationError):
                return error_result(
                    PetHospitalError(
                        ErrorCode.VALIDATION_ERROR,
                        "Invalid list_pets parameters.",
                        validation_details(exc),
                    )
                )
            raise

        try:
            output = await client.list_pets(filters)
            return success_result(output)
        except PetHospitalError as exc:
            return error_result(exc)
        except Exception as exc:  # Never expose a raw Python/HTTPX/Pydantic traceback.
            logger.error("Unexpected list_pets failure (%s)", type(exc).__name__)
            return error_result(
                PetHospitalError(
                    ErrorCode.INTERNAL_ERROR,
                    "An internal error occurred while processing list_pets.",
                    {"reason": type(exc).__name__},
                )
            )

    # The SDK-generated model otherwise defaults to ignoring unknown fields.
    # Tighten the advertised schema; the MCP middleware enforces it on every call.
    tool = server._tool_manager.get_tool("list_pets")  # noqa: SLF001
    if tool is not None:
        tool.parameters["additionalProperties"] = False






