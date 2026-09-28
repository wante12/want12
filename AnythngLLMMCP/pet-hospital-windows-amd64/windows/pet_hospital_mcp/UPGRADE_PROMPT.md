# 第二阶段升级说明

本文件仅描述后续扩展约束；当前仓库仍只实现一个工具 `list_pets`。

## 保留的协议基线

后续新增工具时必须继续使用：

- `mcp==2.0.0`
- MCP `2026-07-28`
- `mcp.server.MCPServer`
- 无状态 Streamable HTTP
- `/mcp` 作为 MCP 端点
- `/health` 健康检查

不得引入 `mcp.server.fastmcp.FastMCP`、旧 `initialize` 流程、`Mcp-Session-Id`、会话存储、会话过期、`max_sessions` 或有状态 SSE 恢复。

## 新增工具方式

1. 在 `src/pet_hospital_mcp/tools/` 新增独立模块。
2. 在模块中定义严格 Pydantic 输入、成功输出和错误输出模型。
3. 复用 `PetHospitalRestClient`、`PetHospitalError`、`ErrorCode` 和结构化结果辅助函数。
4. 在 `server.py` 中显式注册新工具。
5. 不要增加适配器私有业务参数；参数应真实对应 Go REST API。
6. 保持工具名为 `snake_case`。
7. 更新 README 的工具列表、示例和阶段声明。

## 错误与日志要求

- 所有预期失败返回统一错误结构，不向客户端暴露堆栈。
- 后端请求必须保留超时、有限重试和结构化错误映射。
- 工具调用日志继续包含 `timestamp`、`tool_name`、`params`、`status`、`duration_ms`。
- 敏感字段必须继续递归脱敏。

## 测试要求

至少新增：

- 正常请求及全部参数转发
- 输入模型约束
- 后端 4xx/5xx、超时、连接异常
- 非法 JSON 和响应模型不匹配
- 工具注册名称及 JSON Schema
- 2026-07-28 HTTP 发现与调用
- 不出现 `Mcp-Session-Id`，不发送旧 `initialize`

完成标准：

```powershell
pytest -q
```

全部测试通过，且真实 MCP 客户端可以完成 `server/discover`、`tools/list` 和目标工具调用。
