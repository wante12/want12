# 第二个开发任务 · AnythingLLMMCP

给本机 AnythingLLM 写一个 MCP，只实现一个功能：**读取第一个工作区的文件信息**。

## 文件

```
AnythingLLMMCP\
├── server.py         ← MCP 服务（单文件）
├── check.py          ← 两套协议自检
├── requirements.txt
└── .venv\
```

## 前置条件

1. **AnythingLLM 后端在跑**（端口 3001）
2. **有 API Key**：AnythingLLM「设置 → 工具 → 开发者 API」创建

## 启动

```powershell
cd D:\LLM-Course\AnythingLLMMCP
$env:ANYTHINGLLM_API_KEY = "你的Key"
.\.venv\Scripts\python.exe server.py        # 监听 127.0.0.1:8093
```

环境变量：

| 变量 | 默认值 |
|------|--------|
| `MCP_PORT` | `8093` |
| `ANYTHINGLLM_URL` | `http://localhost:3001` |
| `ANYTHINGLLM_API_KEY` | 必填 |

| 端点 | 地址 |
|------|------|
| MCP | `http://127.0.0.1:8093/mcp` |
| 健康检查 | `http://127.0.0.1:8093/health` |

## 工具：list_workspace_files

| 参数 | 说明 |
|------|------|
| `preview_chars` | 每个文件返回多少字预览，0 = 不取（默认，最省 token） |
| `limit` | 最多返回文件数，默认 50，范围 1~200 |

返回：

```json
{
  "workspace": { "name": "我的工作区", "slug": "c14b1d6f-..." },
  "count": 4,
  "files": [
    { "title": "prompt-step1.md-88cc373f-....json",
      "docpath": "custom-documents/prompt-step1.md-88cc373f-....json" }
  ]
}
```

## 验证

```powershell
.\.venv\Scripts\python.exe check.py
```

实测输出：

```
旧版 -> 工作区: 我的工作区 | 文件数: 4
    - prompt-step1.md-88cc373f-....
新版 tools/list -> ['list_workspace_files']
新版 -> 工作区: 我的工作区 | 文件数: 4

两套协议均通过 ✓
```

## 用到的接口

| 用途 | 接口 |
|------|------|
| 取工作区列表，拿第一个 | `GET /api/v1/workspaces` → `workspaces[].slug` |
| 取工作区文件 | `GET /api/v1/workspace/{slug}` → `workspace[0].documents[]` |
| 可选内容预览 | `GET /api/v1/workspace/{slug}/get-document?location=` |

鉴权：`Authorization: Bearer <API Key>`。

> 注意：`GET /api/v1/workspace/{slug}` 返回的是 **`workspace` 数组**（不是对象），
> 文件在 `workspace[0].documents`，字段是 `title` / `docpath`。
> `title` 常为空，代码已回退到 `docpath` 的文件名。

错误码：`VALIDATION_ERROR`、`CONFIG_ERROR`、`UNAUTHORIZED`、`NO_WORKSPACE`、
`BACKEND_UNAVAILABLE`、`BACKEND_TIMEOUT`、`BACKEND_API_ERROR`。

## 排错

| 现象 | 处理 |
|------|------|
| `UNAUTHORIZED` | Key 不对，去开发者 API 重建 |
| `NO_WORKSPACE` | AnythingLLM 里还没有工作区 |
| `BACKEND_UNAVAILABLE` | AnythingLLM 后端没起（端口 3001） |
