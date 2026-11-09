# LLM-Course

三个开发任务的课程环境 + Agent 练习。

```
D:\LLM-Course\
├── PetHospitalServer\     宠物医院服务端（含 pethospital.exe，已随仓库分发）
├── PetHospitalMCP\        任务一：宠物医院 MCP（list_pets）
├── AnythingLLMMCP\        任务二：AnythingLLM MCP（读第一个工作区文件）
├── AnythingLLMWebPage\    任务三：上传网页（上传 + 嵌入）
├── Agent\                 Agent 练习（wAgent 等）
├── BaziMCP\               八字 MCP（bazi-mcp 的 HTTP 托管）
├── Playground\            MCP 客户端配置文件
└── start-all.bat          ★ 一键启动全部服务
```

| # | 内容 | 目录 | 工具 / 形式 | 端口 |
|:-:|------|------|-------------|:----:|
| 1 | 宠物医院 REST | `PetHospitalServer\` | 网页 + 数据源 | 8080 |
| 2 | 宠物医院 MCP | `PetHospitalMCP\` | 工具 `list_pets` | 8090 |
| 3 | 八字 MCP | `BaziMCP\` | 3 个八字工具 | 8095 |
| 4 | AnythingLLM MCP | `AnythingLLMMCP\` | 工具 `list_workspace_files` `workspace_chat` `search_vectors` | 8093 |
| 5 | 上传网页 | `AnythingLLMWebPage\` | `index.html` | — |
| — | Agent | `Agent\wAgent\` | TUI + 16 个本地工具 + MCP 客户端（HTTP/stdio） | — |

两个宠物医院相关的 MCP 都是 **Streamable HTTP，无握手、无会话、无长连接**，
同时兼容 **2026-07-28 之前（旧版 initialize）和之后（单次 POST + `_meta`）** 两套协议。

---

## 一键启动

双击 **`start-all.bat`**，会依次拉起三个服务（每个开独立窗口）：

| 脚本 | 服务 | 端口 |
|------|------|:----:|
| `start-rest.bat` | 宠物医院 REST 后端 | 8080 |
| `start-mcp-pet.bat` | 宠物医院 MCP Server | 8090 |
| `start-mcp-bazi.bat` | 八字 MCP Server | 8095 |

启动顺序有依赖：**REST 必须在 MCP 之前就绪**（脚本已处理 4 秒间隔）。

服务都起来后启动 wAgent：

```powershell
cd D:\office
python D:\LLM-Course\Agent\wAgent\main.py
```

> **关于 `D:\office`**：这是示例项目根目录，不是必须的路径。
> wAgent 以**启动时的工作目录**作为项目根，并从该目录查找三样东西：
>
> | 文件 | 作用 | 缺失时 |
> |------|------|--------|
> | `.mcp.json` | MCP 服务器清单 | 跳过 MCP，只用本地工具 |
> | `AGENTS.md` / `AGENT.md` | 项目约定指令 | 不注入项目指令 |
> | `.agents/skills/` | Agent Skills 目录 | 无技能可加载 |
>
> 所以你可以换成任意目录，只要其中放好自己的 `.mcp.json` 即可。
> 例如想直接在课程仓库里跑：
>
> ```powershell
> cd D:\LLM-Course
> python Agent\wAgent\main.py
> ```
>
> 此时会读取 `D:\LLM-Course\.mcp.json`（若存在）。

三者关闭窗口即停止。端口自查：

```powershell
foreach ($p in 8080,8090,8095) {
  "$p : " + $(if (Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue) {'OK'} else {'DOWN'})
}
```

> `.bat` 里全部使用英文：中文批处理在 `chcp 65001` 下容易解析出错，这是实测踩过的坑。

---

## 前置依赖

部分模块需要外部依赖（课程提供的服务端二进制、运行中的 AnythingLLM）。
这些依赖不随仓库分发，准备方法见 **[DEPENDENCIES.md](DEPENDENCIES.md)**。

---

## 快速开始

### 0. 启动宠物医院服务端

```powershell
cd D:\LLM-Course\PetHospitalServer
.\pethospital.exe                       # 127.0.0.1:8080
```

### 1. 任务一

```powershell
cd D:\LLM-Course\PetHospitalMCP
.\.venv\Scripts\python.exe server.py    # 8090
.\.venv\Scripts\python.exe check.py     # 两套协议自检
```

### 2. 任务二

需要 AnythingLLM 后端在 3001 端口，并且有 API Key。

```powershell
cd D:\LLM-Course\AnythingLLMMCP
$env:ANYTHINGLLM_API_KEY = "你的Key"
.\.venv\Scripts\python.exe server.py    # 8093
.\.venv\Scripts\python.exe check.py
```

### 3. 任务三

双击 `AnythingLLMWebPage\index.html`，填 API Key，拖文件，点「上传并嵌入」。

### 客户端配置

`Playground\mcp.json` 已包含两个服务，直接给 Cherry Studio / MCP Inspector 用。

---

## Agent 练习

```
Agent\
├── Practice01\
│   ├── chat.py            流式聊天（无工具）
│   └── config.ini         ← 填 DeepSeek Key
├── Practice02\
│   ├── chat.py            工具调用：getDate（查本机日期）
│   ├── chat_leapyear.py   工具调用：getDate + isLeapYear（判断闰年）
│   ├── chat_fileops.py    文件操作工具集（读写目录/文件，最多 12 轮）
│   ├── config.ini         ← 填 DeepSeek Key
│   └── Mermaid.mmd        练习产出的流程图（6 MB）
└── wAgent\                ★ 分层架构重构版（core / tui 分离 + Textual TUI）
    ├── core\              业务内核（Agent / 工具 / LLM / 配置，零 UI 耦合）
    ├── tui\               Textual 界面（只消费 core 事件）
    ├── tests\             17 项自动化测试
    ├── main.py            TUI 启动入口
    └── README.md          架构说明与 Web/Desktop 扩展点
```

### wAgent：分层架构版

`Practice02\chat.py` 的工程化重构，业务与界面彻底分离：

```powershell
cd D:\LLM-Course\Agent\wAgent
python -m pip install -r requirements.txt
python main.py               # Textual 终端界面
python -m pytest -q          # 全量自动化测试
```

快捷键：`Enter` 发送 · `Ctrl+R` 重置对话 · `Ctrl+L` 清屏 · `Ctrl+C` 退出。
详细设计见 `wAgent\README.md`。

### 前置：填 Key

`Practice01\config.ini` 和 `Practice02\config.ini` 都要填（格式相同）：

```ini
[llm]
base_url = https://api.deepseek.com/v1
api_key = 你的DeepSeekKey
model = deepseek-chat
```

> ⚠️ 这两个文件里**原本写着明文 Key**，已加入 `.gitignore`，不会被推上 GitHub。
> 但仍建议去 DeepSeek 后台作废旧 Key 重新生成。

### 运行

```powershell
cd D:\LLM-Course\Agent\Practice01
D:\LLM-Course\PetHospitalMCP\.venv\Scripts\python.exe chat.py
```

> 脚本里有一行 `sys.path.insert(0, r"D:\openai")`，会优先从该目录加载 openai。
> 如果本机没有 `D:\openai`，它会自动改用 pip 安装的 openai，不用管。

| 脚本 | 可以试的提问 |
|------|-------------|
| `Practice01\chat.py` | 普通聊天，如「介绍一下 MCP」 |
| `Practice02\chat.py` | 「今天是几号？」→ 会看到 `[调用工具: getDate]` |
| `Practice02\chat_leapyear.py` | 「2024 年是闰年吗？」→ 调用 `isLeapYear` |
| `Practice02\chat_fileops.py` | 「看看当前目录有什么文件」→ 调用 `list_directory` |

`chat_fileops.py` 的工具最多 12 轮、读文本上限 10 万字符，涉及写文件的提问请谨慎。

---

## 本机实测记录

| 项目 | 结果 |
|------|------|
| 任务一双协议 | ✅ 旧版 `2025-06-18` 握手 + 新版 `2026-07-28` 均通过 |
| 任务一数据 | ✅ 查到真实数据（1008 条，`住院中` 1 条） |
| 任务二双协议 | ✅ 读到「我的工作区」4 个文件 |
| 任务三上传 | ✅ `HTTP 200`，文档成功嵌入（4 → 5），测试后已清理 |

---

## 关键踩坑（重要）

### 1. 新版协议要 `params._meta`

2026-07-28 的单次 POST 必须在 `params._meta` 里带：

```json
{
  "io.modelcontextprotocol/protocolVersion": "2026-07-28",
  "io.modelcontextprotocol/clientCapabilities": {}
}
```

并配 `MCP-Protocol-Version` / `Mcp-Method`（`tools/call` 还要 `Mcp-Name`）请求头。
少了会返回 **400 且响应体为空**，很难查。

### 2. `add_tool` 不要包 Pydantic 入参模型

SDK 会把单个参数名当输入 schema 的根（会多出一层 `inp`），
应把字段直接平铺成函数参数，返回类型标 `dict[str, Any]` 才会有 `structuredContent`。

### 3. AnythingLLM 后端手动启动需要三个环境变量

桌面端卡在安装向导时不监听 3001。直接跑后端：

```powershell
cd "D:\anything llm\AnythingLLM\resources\backend"
$env:STORAGE_DIR = "$env:APPDATA\anythingllm-desktop\storage"
$env:DATABASE_URL = "file:$env:APPDATA\anythingllm-desktop\storage\anythingllm.db"
D:\node\node.exe server.js              # 3001
D:\node\node.exe collector.js           # 8888，上传/解析必需
```

缺 `DATABASE_URL` 会导致所有 API Key 校验失败（`No valid api key found`）。

### 4. 上传依赖 collector

`POST /v1/document/upload` 在 collector（8888）未运行时报
`Document processing API is not online`（HTTP 500）。

---


