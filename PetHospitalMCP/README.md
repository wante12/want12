# 第一个开发任务 · PetHospitalMCP

给谢老师的「宠物医院系统」写一个 MCP，只实现 `list_pets`。

## 文件

```
PetHospitalMCP\
├── server.py         ← MCP 服务（约 190 行，单文件）
├── check.py          ← 两套协议自检
├── requirements.txt
└── .venv\
```

## 启动

```powershell
# 1) 先启动宠物医院服务端
cd D:\LLM-Course\PetHospitalServer
.\pethospital.exe                      # 监听 127.0.0.1:8080

# 2) 装依赖（已装好）
cd D:\LLM-Course\PetHospitalMCP
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# 3) 启动 MCP
.\.venv\Scripts\python.exe server.py   # 监听 127.0.0.1:8091
```

| 端点 | 地址 |
|------|------|
| MCP | `http://127.0.0.1:8091/mcp` |
| 健康检查 | `http://127.0.0.1:8091/health` |

环境变量：`MCP_PORT`（默认 8091）、`PET_HOSPITAL_BASE_URL`（默认 `http://127.0.0.1:8080`）。

## 验证

```powershell
.\.venv\Scripts\python.exe check.py
```

实测输出：

```
旧版 initialize -> 2025-06-18
旧版 tools/call -> total: 1 | 例: 咪咪
新版 tools/list -> ['list_pets']
新版 tools/call -> total: 387 | 例: 棉花

两套协议均通过 ✓
```

## 双协议是怎么做到的

`stateless_http=True` + `json_response=True`：

- **无会话**：不出 `Mcp-Session-Id`，每个请求独立处理，没有长连接
- **旧版协议**（2026-07-28 之前）：客户端可以发 `initialize` 握手，也可以直接 POST
- **新版协议**（2026-07-28 及以后）：单次 POST，`params._meta` 携带信封字段，
  并在请求头带 `MCP-Protocol-Version` / `Mcp-Method` / `Mcp-Name`

SDK 按 `MCP-Protocol-Version` 头自动路由到对应处理器，所以同一端口同时支持两套。

> 踩坑记录：新版协议要求在 `params._meta` 里带
> `io.modelcontextprotocol/protocolVersion` 和 `io.modelcontextprotocol/clientCapabilities`，
> 缺了会返回 400（响应体为空）。

## list_pets 参数

`q` `name` `ownerName` `ownerPhone` `species` `doctor` `disease` `status`
`min` `max` `sortBy` `order` `page` `pageSize`

- `species`：犬 / 猫 / 兔 / 鸟 / 仓鼠 / 爬宠 / 其他
- `status`：待就诊 / 就诊中 / 住院中 / 已康复 / 慢性病随访
- `sortBy`：id / name / ownerName / species / doctor / disease / status / totalCost / visitCount / createdAt / updatedAt
- `page >= 1`，`1 <= pageSize <= 500`，`min <= max`

**后端不做校验**（非法值只返回空列表），所以这些约束在 MCP 层自己校验，
不合法直接返回 `VALIDATION_ERROR`。

返回后端 `data`：`items` / `total` / `page` / `pageSize` / `totalPages` / `totalCost`。
`records`、`charges` 为 null 时统一成 `[]`。

错误码：`VALIDATION_ERROR`、`BACKEND_TIMEOUT`、`BACKEND_UNAVAILABLE`、
`BACKEND_API_ERROR`、`BACKEND_INVALID_RESPONSE`。
