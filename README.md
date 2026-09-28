<div align="center">

**课程实践项目集 · 宠物医院 MCP 系统 / LLM 对接 / 文档上传**

</div>

---

## 项目结构

```
Anything/
├── README.md               ← 本文件
├── Pet/                    ← 第一次课：宠物医院完整系统
├── LLM_MCP/                ← 第二次课：AnythingLLM MCP 桥接
└── LLM_UPLOAD_MCP/         ← 第三次课：AnythingLLM 文档上传页
```

| 目录 | 课程 | 简介 | 启动方式 |
|:----:|:----:|------|----------|
| `Pet/` | 第 1 次 | Go 宠物医院 + 28 个 MCP 工具 + AI 对话网页 | 双击 `Pet/启动.bat` |
| `LLM_MCP/` | 第 2 次 | 将 AnythingLLM 知识库封装为 MCP 工具 | `python server.py` |
| `LLM_UPLOAD_MCP/` | 第 3 次 | 文档上传 & 嵌入 AnythingLLM 的网页 | 浏览器直接打开 `index.html` |

---

## Pet — 宠物医院 AI 系统（第 1 次课）

> 一个完整的本地宠物医院管理系统：**Go REST API + Python MCP 服务 + AI 对话网页**，
> 通过自然语言即可查询、修改宠物医院数据。

### 架构

```
┌──────────────────────────────────────────────────────┐
│                浏览器网页 (port 3000)                  │
│     设置页（AI 配置 / MCP 开关）+ 对话页（AI 聊天）      │
└──────────────────┬───────────────────────────────────┘
                   │ HTTP
┌──────────────────▼───────────────────────────────────┐
│              Web 后端 (Python, port 3000)             │
│     静态托管 · AI 流式代理 · MCP 会话管理 · 配置持久化   │
└──────┬───────────────────────────────┬───────────────┘
       │ AI SSE 流                     │ MCP JSON-RPC
┌──────▼──────────┐          ┌─────────▼───────────────┐
│  自定义 AI 接口   │          │  MCP 服务 (port 9000)    │
│ (OpenAI 兼容)    │          │  28 个中文命名工具        │
└─────────────────┘          └─────────┬───────────────┘
                                       │ REST
                             ┌─────────▼───────────────┐
                             │  Go 宠物医院 (port 8080)  │
                             │  29 个 REST API 接口      │
                             │  单文件数据库 data/pet.db  │
                             └─────────────────────────┘
```

### 一键启动

```powershell
# 双击即可
Pet\启动.bat
```

或手动分步启动：

```powershell
# 1. Go 后端 (端口 8080)
cd Pet\windows
.\pethospital.exe

# 2. MCP 服务 (端口 9000)
python Pet\mcp_launcher.py

# 3. Web 服务 (端口 3000)
python Pet\web\server.py
```

启动后打开 **<http://127.0.0.1:3000>**。

### 使用流程

1. **设置页** → 填写 AI 接口（Base URL / API Key / 模型）
2. **设置页** → 点击「刷新 MCP 连接」，勾选要启用的工具（默认全关）
3. **对话页** → 直接输入自然语言，如「查询所有金毛犬」「给旺财添加一条病历」

### 28 个 MCP 工具

| 类别 | 工具名 |
|------|--------|
| 档案 | 查询宠物列表 · 获取宠物详情 · 新增宠物 · 全量更新宠物 · 局部更新宠物 · 删除宠物 |
| 查询 | 全文搜索 · 按主人查询 · 按医生查询 · 按种类查询 · 按疾病查询 · 按状态查询 · 消费排行榜 · 按花费区间查询 |
| 病历 | 查看病历 · 添加病历 |
| 收费 | 查看收费明细 · 添加收费 · 费用汇总 |
| 统计 | 经营统计 · 元数据字典 |
| 管理 | 批量新增 · 批量删除 · 导出数据 · 压实数据库 · 生成模拟数据 · 接口清单 · 健康检查 |

### 配置说明

| 文件 | 说明 |
|------|------|
| `Pet/web/config.json` | AI 接口（`baseUrl` / `apiKey` / `model`）与已启用的 MCP 工具列表 |

环境变量（可选）：

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `WEB_PORT` | `3000` | Web 服务端口 |
| `MCP_PORT` | `9000` | MCP 服务端口 |
| `MCP_URL` | `http://127.0.0.1:9000` | Web 后端访问 MCP 的地址 |
| `PET_HOSPITAL_BASE_URL` | `http://127.0.0.1:8080` | MCP 访问 Go 后端的地址 |

### 目录详情

```
Pet/
├── 启动.bat                # 一键启动入口
├── start.py                # 启动编排（Go + MCP + Web）
├── mcp_launcher.py         # MCP 独立启动入口
├── windows/
│   ├── pethospital.exe     # Go 宠物医院（已内嵌网页）
│   └── data/pet.db         # 单文件数据库（约 1000 条测试数据）
├── pet_hospital_mcp/
│   ├── src/pet_hospital_mcp/
│   │   ├── server.py       # MCP 服务（28 个工具注册）
│   │   ├── rest_client.py  # 通用 HTTP 客户端（GET/POST/PUT/PATCH/DELETE）
│   │   └── tools/          # 工具实现（按功能分 7 个模块）
│   └── tests/              # pytest 测试
└── web/
    ├── server.py           # Web 后端（静态托管 + AI/MCP 代理）
    └── frontend/index.html # 单页前端（设置页 + 对话页）
```

### 技术栈

- **后端**：Go 标准库（零第三方依赖）· Python 3.10+ · `mcp` SDK · `uvicorn`
- **前端**：原生 HTML / CSS / JavaScript（单文件，无构建步骤）
- **协议**：MCP Streamable HTTP · OpenAI 兼容 Chat Completions SSE

---

## LLM_MCP — AnythingLLM MCP 桥接（第 2 次课）

将 **AnythingLLM** 知识库封装为一个 MCP 工具，供 AI 客户端调用。

```powershell
python LLM_MCP\server.py
```

- **工具**：`query_mods(question)` — 向 AnythingLLM 的 `mods` 工作区提问，返回基于文档的 AI 回答
- **依赖**：本地运行的 AnythingLLM（默认 `http://localhost:3001`）
- **传输**：Streamable HTTP

---

## LLM_UPLOAD_MCP — 文档上传页（第 3 次课）

一个纯前端页面，将本地文档上传到 AnythingLLM 并完成向量嵌入。

```
浏览器直接打开 LLM_UPLOAD_MCP/index.html
```

- 支持多文件批量上传
- 自动获取工作区 → 上传文档 → 触发嵌入（embedding）
- 实时显示每一步状态

---

## 通用要求

| 依赖 | 版本 | 用途 |
|------|------|------|
| Python | 3.10+ | MCP 服务 / Web 后端 |
| Go | 1.22+ | 仅重新编译 Go 后端时需要（已有编译好的 exe） |
| Node.js | 不需要 | 前端为原生 JS，无构建步骤 |

Python 依赖：

```powershell
pip install mcp httpx uvicorn
```

---

## License

MIT
