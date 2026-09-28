# Pet Hospital MCP

独立的 Python MCP 服务，把现有 Go 宠物医院 REST API 的 `GET /api/v1/pets` 暴露为唯一的 MCP 工具 `list_pets`。

本阶段只实现只读查询，不修改 Go 服务，不实现任何第二阶段工具。

## 技术基线

- Python 3.11+
- 官方 Python SDK：`mcp==2.0.0`
- MCP 协议：`2026-07-28`
- 服务端类型：`mcp.server.MCPServer`
- 传输：无状态 Streamable HTTP
- 后端 HTTP 客户端：`httpx`
- 输入/输出校验：Pydantic 2

本项目不导入或使用 `mcp.server.fastmcp.FastMCP`。2026-07-28 请求是独立的单次 POST：不发送 `initialize`，不使用 `Mcp-Session-Id`，不创建会话存储或过期机制，也不使用有状态 SSE 恢复。旧协议的 `initialize`/`notifications/initialized` 会被显式拒绝。

## 目录结构

```text
pet_hospital_mcp/
├── pyproject.toml
├── README.md
├── UPGRADE_PROMPT.md
├── src/
│   └── pet_hospital_mcp/
│       ├── __init__.py
│       ├── __main__.py
│       ├── config.py
│       ├── errors.py
│       ├── logging_config.py
│       ├── middleware.py
│       ├── rest_client.py
│       ├── server.py
│       └── tools/
│           ├── __init__.py
│           └── list_pets.py
└── tests/
    ├── conftest.py
    ├── test_config_and_models.py
    ├── test_mcp_http.py
    └── test_rest_client.py
```

## 前置条件

先启动现有 Go 宠物医院服务，默认地址为 `http://127.0.0.1:8080`：

```powershell
cd ..
.\pethospital.exe
```

确认后端可用：

```powershell
Invoke-RestMethod http://127.0.0.1:8080/health
```

## 安装

在 `pet_hospital_mcp` 目录中执行：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
```

开发与测试环境：

```powershell
python -m pip install -e ".[test]"
```

## 配置与启动

支持以下环境变量：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `MCP_HOST` | `127.0.0.1` | MCP 监听地址 |
| `MCP_PORT` | `8000` | MCP 监听端口 |
| `PET_HOSPITAL_BASE_URL` | `http://127.0.0.1:8080` | Go REST API 根地址 |
| `PET_HOSPITAL_TIMEOUT_SECONDS` | `5` | 单次后端请求超时 |
| `PET_HOSPITAL_MAX_ATTEMPTS` | `3` | 后端有限重试次数 |
| `PET_HOSPITAL_RETRY_BACKOFF_SECONDS` | `0.1` | 重试退避基数 |
| `MCP_LOG_LEVEL` | `INFO` | 日志级别 |

启动示例：

```powershell
$env:MCP_HOST = "127.0.0.1"
$env:MCP_PORT = "8000"
$env:PET_HOSPITAL_BASE_URL = "http://127.0.0.1:8080"
python -m pet_hospital_mcp
```

服务端点：

- MCP：`http://127.0.0.1:8000/mcp`
- 健康检查：`http://127.0.0.1:8000/health`

健康检查示例：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

预期响应包含：

```json
{
  "status": "healthy",
  "service": "pet-hospital-mcp",
  "version": "1.0.0",
  "protocolVersion": "2026-07-28",
  "sdk": "mcp==2.0.0"
}
```

教学范围明确不实现认证、权限、CORS 或 Origin/Host 校验。服务默认仍只监听 `127.0.0.1`。

## `list_pets`

工具名称固定为 `list_pets`，调用 Go API：

```text
GET /api/v1/pets
```

支持且仅支持以下参数：

| 参数 | 约束/说明 |
| --- | --- |
| `q` | 关键词 |
| `name` | 宠物姓名 |
| `ownerName` | 主人姓名 |
| `ownerPhone` | 主人电话 |
| `species` | `犬`、`猫`、`兔`、`鸟`、`仓鼠`、`爬宠`、`其他` |
| `doctor` | 医生 |
| `disease` | 疾病/诊断 |
| `status` | `待就诊`、`就诊中`、`住院中`、`已康复`、`慢性病随访` |
| `min` | 最低总花费，非负 |
| `max` | 最高总花费，非负；必须 `min <= max` |
| `sortBy` | `id`、`name`、`ownerName`、`species`、`doctor`、`disease`、`status`、`totalCost`、`visitCount`、`createdAt`、`updatedAt` |
| `order` | `asc` 或 `desc` |
| `page` | 从 1 开始，默认 `1` |
| `pageSize` | `1..500`，默认 `20` |

输入模型拒绝未知字段、类型错误、NaN、Infinity 及超范围值。成功输出严格对应 Go API 成功响应的 `data`：

```text
items, total, page, pageSize, totalPages, totalCost
```

`items[].records` 和 `items[].charges` 均兼容 `null` 或数组。

## 使用官方 Python SDK 2.x 验证

启动 MCP 服务后运行：

```python
import asyncio

from mcp import Client


async def main() -> None:
    async with Client("http://127.0.0.1:8000/mcp") as client:
        tools = await client.list_tools()
        print(client.protocol_version)  # 2026-07-28
        print([tool.name for tool in tools.tools])

        result = await client.call_tool(
            "list_pets",
            {
                "species": "犬",
                "min": 1000,
                "sortBy": "totalCost",
                "order": "desc",
                "page": 1,
                "pageSize": 2,
            },
        )
        print(result.is_error)
        print(result.structured_content["total"])
        print(result.structured_content["items"])


asyncio.run(main())
```

也可以使用 MCP Inspector：启动 MCP 服务后打开 Inspector，选择 Streamable HTTP，URL 填入 `http://127.0.0.1:8000/mcp`，然后发现并调用 `list_pets`。

## 统一错误结构

工具错误使用结构化 `CallToolResult`，并设置 2.0.0 实际支持的 `is_error=True`：

```json
{
  "error": {
    "code": "ERROR_CODE",
    "message": "可读错误信息",
    "details": {}
  }
}
```

错误码：

- `VALIDATION_ERROR`
- `BACKEND_TIMEOUT`
- `BACKEND_UNAVAILABLE`
- `BACKEND_API_ERROR`
- `BACKEND_INVALID_RESPONSE`
- `INTERNAL_ERROR`

HTTPX、Pydantic、SDK 或 Python 堆栈不会原样返回给 MCP 客户端。

## 日志

日志使用 JSON 输出，工具调用至少包含：

```text
timestamp, tool_name, params, status, duration_ms
```

`ownerPhone`、`ownerAddr`、`chipNo` 以及对应 snake_case 字段会递归脱敏为 `[REDACTED]`。

## 测试

在 `pet_hospital_mcp` 目录执行：

```powershell
pytest -q
```

当前真实结果：

```text
39 passed
```

测试使用 `httpx.MockTransport`，不会访问真实 Go 服务。覆盖参数转发、输入约束、后端 4xx/5xx、超时/连接错误、非法 JSON/响应模型、工具名称与 Schema、2026-07-28 无状态发现/列表/调用、无 `Mcp-Session-Id`、旧 `initialize` 拒绝和 `/health`。

## 阶段声明

本服务明确未实现阶段二工具。当前 MCP 工具清单只有 `list_pets`。
