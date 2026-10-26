# Playground

MCP 客户端（Cherry Studio / Claude Desktop / MCP Inspector 等）的配置文件。

## mcp.json

```json
{
  "mcpServers": {
    "pet-hospital": { "type": "streamableHttp", "url": "http://127.0.0.1:8091/mcp" },
    "anythingllm":  { "type": "streamableHttp", "url": "http://127.0.0.1:8093/mcp" }
  }
}
```

| 服务 | 端口 | 来自 | 工具 |
|------|:----:|------|------|
| `pet-hospital` | 8091 | `..\PetHospitalMCP\server.py` | `list_pets` |
| `anythingllm` | 8093 | `..\AnythingLLMMCP\server.py` | `list_workspace_files` |

两者都是 **Streamable HTTP**、无握手、无会话，同时兼容 2026-07-28 前后两套协议。

## 使用前提

两个 MCP 服务都要先启动，再让客户端读取本配置：

```powershell
# MCP 1（需先启动 pethospital.exe）
cd ..\PetHospitalMCP; .\.venv\Scripts\python.exe server.py

# MCP 2（需 AnythingLLM 已运行 + 设置 API Key）
cd ..\AnythingLLMMCP
$env:ANYTHINGLLM_API_KEY = "你的Key"
.\.venv\Scripts\python.exe server.py
```

不放心的可以先跑各自的 `check.py` 自检两套协议。
