# wAgent · Agent（core / tui 分层架构）

基于 `Practice02/chat.py` 重构：**业务内核与界面完全分离**，同一套 core 可被 TUI / Web / Desktop 复用。

> 本项目复制自 `Agent/Practice02`，路径已完全独立，可单独运行与提交。

---

## 目录结构

```
wAgent/
├── config.ini              # LLM + 搜索配置（含 Key，已被 .gitignore 排除）
├── requirements.txt
├── main.py                 # TUI 启动入口（含 Skill 扫描）
├── pytest.ini
│
├── core/                   # ★ 业务内核：与界面零耦合
│   ├── __init__.py         #   只暴露 build_agent / AgentEvent
│   ├── app.py              #   装配入口（Composition Root）
│   ├── config.py           #   配置加载 + 校验
│   ├── events.py           #   ★ 领域事件契约（core ↔ UI 唯一接口）
│   ├── agent/
│   │   └── engine.py       #   对话循环、工具编排、消息管理
│   ├── llm/
│   │   └── client.py       #   LLMClient 抽象 + OpenAI 实现
│   ├── skills/             # ★ Agent Skills 发现与注册
│   │   ├── models.py       #   Skill / SkillLoadError
│   │   ├── loader.py       #   frontmatter 解析 + 目录扫描 + 正文加载
│   │   ├── prompt.py       #   技能清单 → System Prompt 片段
│   │   └── registry.py     #   SkillRegistry
│   ├── mcp/                # ★ MCP 客户端
│   │   ├── config.py       #   .mcp.json 解析
│   │   ├── client.py       #   后台事件循环 + Server 长连接
│   │   ├── manager.py      #   连接管理 / 工具发现 / 命名冲突
│   │   ├── tools.py        #   MCP 工具 → 本地 Tool 包装
│   │   └── prompt.py       #   MCP 状态 → System Prompt 片段
│   └── tools/
│       ├── base.py         #   Tool 抽象 + ToolRegistry
│       ├── builtin.py      #   getDate 工具
│       ├── search.py       #   searchWeb 联网搜索工具
│       ├── fetch.py        #   fetchWeb 网页正文抓取工具
│       ├── filesystem.py   #   9 个文件系统工具
│       ├── skill.py        #   loadSkill 按需加载技能正文
│       ├── create_skill.py #   createSkill 新建技能
│       └── cli.py          #   RunCli 本地命令执行工具
│
├── tui/                    # ★ Textual 界面：只消费事件
│   ├── __init__.py
│   ├── app.py              #   主界面（布局/流式渲染/命令分发）
│   ├── theme.tcss          #   样式：配色与左侧色条
│   ├── commands.py         #   斜杠命令解析
│   ├── screens/
│   │   └── help.py         #   /help 弹窗
│   └── widgets/
│       ├── message.py      #   用户 / 助手 / 错误 气泡
│       ├── tool_card.py    #   可折叠工具卡片（参数 + 结果 + 耗时）
│       ├── sidebar.py      #   右侧栏（会话 / 工具 / 技能）
│       └── status_bar.py   #   底部状态栏（轮次 / 工具次数 / 耗时）
│
└── tests/
    ├── test_core.py        # core 单元测试（假 LLM，无网络）
    ├── test_search.py      # searchWeb 工具测试（模拟 HTTP，离线）
    ├── test_fetch.py       # fetchWeb 工具测试（模拟 curl，离线）
    ├── test_cli.py         # RunCli 工具测试（真实轻量命令）
    ├── test_filesystem.py  # 9 个文件系统工具测试（tmp_path 隔离）
    ├── test_skills.py      # Skill 发现与注册测试
    ├── test_skill_prompt.py # Skill 注入 Prompt 与 loadSkill 测试
    ├── test_skill_files.py  # loadSkill 的 filename 解析测试
    ├── test_skill_integration.py # 动态加载原则 + 工具协同
    ├── test_create_skill.py # createSkill 工具测试
    ├── test_mcp.py         # MCP 客户端测试（含真实连接）
    ├── test_main_config.py # 启动配置测试
    └── test_tui.py         # TUI 无头测试
```

> 同目录的 `chat.py` / `chat_leapyear.py` / `chat_fileops.py` / `Mermaid.mmd`
> 是 Practice02 原有的练习文件，未纳入新架构，保留备查。

---

## 工具

| 工具 | 用途 | 依赖 |
|------|------|------|
| `getDate` | 读取本机日期时间 | 无 |
| `searchWeb` | 联网搜索最新信息 | 千帆 API Key |
| `fetchWeb` | 获取网页正文 | 本地 curl + trafilatura |
| `RunCli` | 执行本地命令行程序 | 无（需命令已安装） |

### 文件系统工具（9 个）

全部用 Python 标准库实现，不调用外部命令——中文路径、空格路径与错误类型都更可控。

| 工具 | 作用 | 关键参数 |
|------|------|----------|
| `getCwd` | 获取当前工作目录 | — |
| `listDir` | 列出目录下的文件与子目录 | `path`、`recursive` |
| `getFileType` | 文件类型（扩展名 / MIME / 文本或二进制 / 大小） | `path` |
| `readFile` | 读取纯文本文件内容 | `path` |
| `createFile` | 按目录 + 文件名创建新文件 | `directory`、`filename`、`content` |
| `editFile` | 编辑纯文本文件 | `path`、`content`、`mode` |
| `createDir` | 创建目录（自动建上级） | `path` |
| `deleteDir` | 删除目录（支持非空） | `path` |
| `deleteFile` | 删除文件 | `path` |

设计要点：

- **只读工具不落空**：`readFile` / `editFile` 遇到二进制文件会拒绝并提示用 `RunCli`
- **`createFile` 不覆盖**：文件已存在时报错，引导改用 `editFile`
- **`createFile` 不建父目录**：缺目录时提示先用 `createDir`，避免路径打错却静默成功
- **文本编码**：UTF-8 → GBK → 有损兜底，中文文件不会乱码
- **二进制判定**：前 8 KB 含 NUL 字节，或无法按 UTF-8/GBK 解码
- **`editFile` 两种模式**：`overwrite` 整体覆盖、`append` 追加末尾

配置（可选）：

```ini
[fs]
max_read_chars = 20000
max_list_entries = 500
```

#### ⚠️ 删除操作的保护

`deleteDir` / `deleteFile` **不可恢复**。除请求确认外，代码层面还有兜底：
拒绝删除**文件系统根目录**、**当前工作目录**及其**上级目录**。

按教学要求，除此之外不设目录白名单——路径以运行 Agent 的用户权限为准。

### searchWeb

调用百度千帆「智能搜索生成」API，把结果整理成 **摘要 + 参考来源（标题/URL）** 返回给模型。

```json
{"query": "搜索关键词或自然语言问题"}
```

返回格式：

```
关于「xxx」的搜索结果：

[1] 标题（站点 · 日期）
摘要文本…

参考来源：
[1] 标题 - https://...
```

模型会根据系统提示词**自行判断**何时需要联网（时事、新闻、实时数据、超出知识范围的问题）。

### 搜索配置

`config.ini` 增加 `[search]` 段：

```ini
[search]
baidu_qianfan_api_key = bce-v3/ALTAK-xxx/yyy
```

可选配置项（一般不用改）：

| 键 | 默认值 | 说明 |
|----|--------|------|
| `endpoint` | `https://qianfan.baidubce.com/v2/ai_search/chat/completions` | 接口地址 |
| `resource_id` | `ai_search` | 固定 |
| `search_source` | `baidu_search_v2` | 搜索源 |
| `top_k` | `5` | 返回给模型的来源条数 |
| `timeout_seconds` | `20` | 请求超时 |

> Key 在 [百度智能云控制台](https://console.bce.baidu.com/) 创建，**代码中不硬编码**。
> 缺少 `[search]` 段或 Key 为空不会导致启动失败，只会在调用时向模型返回配置提示。

### 错误处理

工具**从不抛异常**，所有失败都转成可读文本回传给模型（保证对话不中断）：

| 场景 | 返回给模型的信息 |
|------|------------------|
| 未配置 Key | 提示缺少 `baidu_qianfan_api_key` 及配置位置 |
| `query` 为空 | `搜索失败：query 不能为空` |
| 网络/DNS 失败 | `网络连接失败（...），请检查网络或代理设置` |
| 超时 | `请求超时（超过 N 秒），请稍后重试` |
| 401 / 403 / 429 / 5xx | 翻译成中文原因（Key 无效 / 无权限 / 限流 / 服务端错误） |
| 返回非 JSON | `接口返回的不是合法 JSON：...` |
| 业务错误码 | `接口业务错误 code=xxx: message` |
| 无结果 | `未找到与「xxx」相关的搜索结果` |

系统提示词要求模型在工具报错时**如实告知用户**，不得假装搜索成功。

### fetchWeb

获取指定网页的**正文**，用于在 `searchWeb` 拿到链接后深入阅读。

```json
{"url": "https://example.com/article"}
```

工作流程：

1. `subprocess` 以**参数列表**方式调用本地 `curl` 取回 HTML（**不使用 `shell=True`**）
2. `trafilatura` 提取正文并转 Markdown
3. 返回「来源 URL + 正文 Markdown」

自动去除**导航栏、广告、页脚、评论区**，保留：

| 保留项 | 说明 |
|--------|------|
| 标题 | `#` / `##` 层级 |
| 段落 | 原文分段 |
| 列表 | `-` / `1.` |
| 表格 | Markdown `|` 表格 |
| 链接 | `[文字](url)` |

默认上限 12000 字符，超出会在段落边界截断并注明。

#### 抓取配置

`config.ini` 可选 `[fetch]` 段（不填则用默认值）：

```ini
[fetch]
timeout_seconds = 20
max_chars = 12000
curl_path = curl
```

> Windows 10+ 自带 `curl.exe`。若 `curl_path` 找不到程序，工具会返回明确提示。
> 注意 PowerShell 里 `curl` 是 `Invoke-WebRequest` 的别名，但本工具走 Python
> `subprocess`，用的是真正的 `curl.exe`。

#### 错误处理

| 场景 | 返回给模型的信息 |
|------|------------------|
| `url` 为空 | `抓取失败：url 不能为空` |
| 协议不合法 | 要求以 `http://` / `https://` 开头 |
| 找不到 curl | 提示安装 curl 或用 `curl_path` 指定路径 |
| 域名解析失败 | `无法解析域名...curl 退出码 6` |
| 连接失败 / SSL / 重定向过多 | 按 curl 退出码翻译（7 / 35 / 47 等） |
| 超时 | `请求超时，curl 退出码 28` |
| HTTP 4xx / 5xx | `网页返回 HTTP 404（未找到，请检查网址）` |
| 响应为空 | `网页返回内容为空` |
| HTML 解析异常 | `HTML 解析出错（...）` |
| 提取不到正文 | 提示可能是 JS 渲染 / 需登录 / 非文章页 |
| 缺少 trafilatura | 提示 `pip install trafilatura` |

> **已知限制**：部分站点对不存在的页面返回 **HTTP 200 + 导航内容**（软 404），
> 此时状态码检测无法识别，只能依赖正文提取。这是网站行为，非工具缺陷。

### RunCli

执行本地已安装的任意命令行程序，把 **stdout / stderr / 退出码** 一起返回给模型，
使其能判断执行结果并决定下一步。

```json
{"command": "python", "args": ["--version"]}
```

实现要点：

```python
argv = [command, *args]
subprocess.run(argv, shell=False, capture_output=True, timeout=...)
```

- **参数列表执行**，命令行字符串从不拼接 → 无 shell 注入
- **`shell=False`**，含空格 / `;` / `$` 的参数原样传给程序，不被解释
- 捕获 stdout / stderr，不污染 TUI 界面
- **返回退出码**：`0（成功）` / 非 0 `（失败）`

返回格式：

```
命令：cmd /c dir /b *.py
退出码：0（成功）

--- stdout ---
wAgent.py

--- stderr ---
（有错误时才出现）
```

#### 超时与截断

| 机制 | 默认值 | 说明 |
|------|--------|------|
| `timeout_seconds` | 15 | 超时后终止进程，**已产出的输出仍会返回** |
| `max_output_chars` | 4000 | stdout / stderr 各自上限 |

超长输出采用**保留开头 + 结尾**的策略，中间标注省略：

```
AAAA...（中间省略 72 字符）...BBBB
TAIL_ERROR
（stdout 过长已截断，省略 72 字符）
```

> 保留尾部是因为**报错信息通常出现在输出末尾**，只截头部会丢掉关键错误。

#### 配置

```ini
[cli]
timeout_seconds = 15
max_output_chars = 4000
workdir = 
```

`workdir` 留空则继承 Agent 进程的当前目录。

#### 错误处理

| 场景 | 返回给模型的信息 |
|------|------------------|
| `command` 为空 | `执行失败：command 不能为空` |
| `args` 不是列表 | `执行失败：args 必须是字符串列表，收到的是 str` |
| 程序不存在 | `执行失败：找不到程序「xxx」，请确认已安装并在 PATH 中` |
| 无执行权限 | `执行失败：没有权限执行「xxx」` |
| 超时 | `执行超时：命令在 15 秒内未结束，已被终止` + 已捕获输出 |
| 非 0 退出码 | 正常返回，含退出码与 stderr（由模型判断原因） |

#### ⚠️ 安全边界

按教学设计，本工具**不设命令白名单 / 黑名单 / 审批机制**，命令以运行 Agent 的
**当前用户权限**执行。这意味着模型可以执行该用户能执行的任何命令，
包括删除文件或访问网络。

**仅适用于受控的教学实验环境**。如需用于其他场景，建议在 `RunCliTool.run()`
入口增加白名单校验，或在 TUI 层加入人工确认步骤。

#### 实测演示

模型会**根据错误反馈自我纠正**，这正是本工具的教学目的：

```
[调用 RunCli] {'command': 'ls', 'args': ['-la']}
[返回] 执行失败：找不到程序「ls」。请确认该命令已安装并在 PATH 中

[调用 RunCli] {'command': 'cmd', 'args': ['/c', 'dir /b *.py']}
[返回] 命令：cmd /c dir /b *.py
       退出码：0（成功）
       --- stdout --- wAgent.py ...
```

---

## 运行

```powershell
cd D:\LLM-Course\Agent\wAgent
python -m pip install -r requirements.txt
python wAgent.py
```

### 界面布局

```
┌────────────────────────────────────────────┬──────────────────┐
│ wAgent · 4 个工具 · deepseek-chat           │ 会话             │
│ 工作目录  D:\LLM-Course\Agent\wAgent        │ 模型   deepseek… │
│ Enter 发送  /help 命令  Esc 中断生成 …      │ 会话   f4e89d3a  │
├────────────────────────────────────────────┤ 轮次   1         │
│                                             │ 消息   3         │
│ ▌你          ← 橙色左条                     │ 上限   5         │
│   今天是几号？                               │ 状态   就绪      │
│                                             │                  │
│ ▌xAgent      ← 蓝色左条（流式逐字出现）      │ 工具 · 4         │
│   今天是 2026 年 10 月 26 日…                │ • getDate        │
│                                             │   获取当前日期…  │
│ ▌getDate() · 32 ms  ← 绿色左条，可展开       │ • searchWeb      │
│   参数 {}                                   │   联网搜索…      │
│   结果 周一 2026/10/26                       │                  │
│                                             │                  │
├────────────────────────────────────────────┴──────────────────┤
│ > 输入问题后回车发送；/help 查看命令                           │
├───────────────────────────────────────────────────────────────┤
│ ● 就绪 · 1 轮 · deepseek-chat · 工具 1 次 · 2.5s · Esc 中断    │
└───────────────────────────────────────────────────────────────┘
```

- **左侧色条区分角色**：橙=用户，蓝=助手，绿=工具，红=错误，黄=工具执行中
- **工具卡片可折叠**：标题显示 `名称(参数) · 耗时`，展开看参数 JSON 与完整结果
- **流式渲染**：模型逐字输出，工具执行中卡片显示「运行中…」
- **状态栏实时统计**：轮次、工具调用次数、本轮耗时

### 快捷键

| 按键 | 功能 |
|------|------|
| `Enter` | 发送 |
| `Esc` | 中断当前生成 |
| `Ctrl+L` | 清屏（保留历史） |
| `Ctrl+N` | 新建会话（重置历史） |
| `Ctrl+B` | 显示/隐藏侧栏 |
| `F1` | 帮助 |
| `Ctrl+Q` | 退出 |

### 斜杠命令

| 命令 | 作用 |
|------|------|
| `/help` | 打开帮助 |
| `/clear` | 清空界面（保留历史） |
| `/new` | 新建会话（重置历史） |
| `/tools` | 列出已注册工具 |
| `/cwd` | 显示工作目录 |
| `/model` | 显示模型与配置路径 |
| `/quit` | 退出 |

测试：

```powershell
python -m pytest -q
# 139 passed
```

---

## Agent Skills

按 [Agent Skills](https://agentskills.io) 规范加载本地技能。启动时以**当前工作目录**为项目根：

```
<项目根>/.agents/skills/<skill-name>/SKILL.md
```

### SKILL.md 格式

```markdown
---
name: 撰写通知
description: 撰写公司内部通知
---

1. 标题必须包含部门名称……
```

- `name`、`description` 为**必需字段**，缺失或为空会跳过该 Skill
- 其余字段（`version`、`layout` 等）原样保留在 `Skill.extra`，不影响加载
- `description` 支持 YAML 块标量（`|`），多行会被压平显示

### 只读元信息

按规范要求，**初始化阶段只读取 frontmatter**。实现上 `read_frontmatter()`
逐行扫描到结束 `---` 就停止，**正文根本不会被读入内存**——
即使正文是非法内容也不影响加载（`test_body_is_not_read` 专门验证这一点）。

### 容错

- `.agents/skills` 不存在 → 返回空列表，不影响启动
- 单个 Skill 损坏 → 记录到 `registry.errors` 并跳过，其余照常加载
- 两个 Skill 同名 → 保留目录名排序靠前者，另一个记为冲突

启动时会把跳过的 Skill 打印到 stderr；TUI 里可用 `/skills` 查看。

### 注入 System Prompt

启动时把技能清单拼到 System Prompt 末尾，让模型知道有哪些技能、怎么按需加载：

```
You have access to the following skills:
- 'fortune-daily': 每日综合运势预测技能 — 融合西方星座 + 中国生肖…
- '撰写通知': 撰写公司内部通知

Use the 'loadSkill' tool to load the full instructions of a skill when needed.
You can also load additional files referenced by a skill.
Only load a skill when it is relevant to the current task; do not load every skill up front.
Skills work alongside your other tools: use the regular tools for files, commands and web
access, and load a skill only for its task-specific guidance.
```

要点：

- **只放名称与描述**，正文不进 Prompt，避免常驻 token 开销
- 描述压平成单行，多行 YAML 块标量不会把清单撑开
- **没有技能时整段不注入**，Prompt 保持原样
- 技能段在 `Agent.reset()` 后仍然保留

### 动态加载原则

**Skill 正文只在模型调用 `loadSkill` 时才进入对话上下文。** 具体保证：

| 阶段 | 上下文里有什么 |
|------|----------------|
| 启动后 | System Prompt 只有 `name` + `description` |
| 模型请求第 1 次 | 仍只有元信息，含正文的技能段不存在 |
| 调用 `loadSkill` 后 | 正文作为 **`tool` 消息**进入，模型下一次请求才能看到 |

这条由测试锁定（`test_body_absent_before_load_skill` /
`test_model_sees_body_on_next_turn`）：断言的是一段独有的正文标记
`SECRET-SKILL-BODY-9f3a` 在加载前后是否出现在上下文里。

### 与已有工具协同

Skill **不改变 Agent 的工作流**：`loadSkill` 只是一个普通 Tool，
和 `RunCli`、`readFile`、`listDir` 走同一条 `registry.execute()` 通道。

- Agent 引擎里**没有**任何 `skill` 相关的特殊分支
- 轮次上限、工具结果回填、失败回滚、消息历史结构全部沿用原逻辑
- 同一轮内可以混用：先 `listDir` 再看目录、再 `loadSkill` 取技能说明

实测（一次对话里文件工具与技能工具并用）：

```
[调用 listDir]  {'path': '.agents/skills'}
  → 目录：D:\office\.agents\skills（共 2 项） [目录] fortune-daily-1.0.1/ [目录] notice/
[调用 loadSkill] {'name': '撰写通知'}
  → 技能「撰写通知」的完整说明：1. 标题必须加入部门名称…… 2. 落款必须写明起草人……

历史角色: system, user, assistant, tool, assistant, tool, assistant
```

消息角色序列就是标准的工具调用循环，与引入 Skill 之前完全一致。

### loadSkill 工具

模型判断某个技能与当前任务相关时，主动调用：

```json
{"name": "撰写通知"}
{"name": "fortune-daily", "filename": "MEMORY.md"}
```

| 参数 | 必填 | 说明 |
|------|:----:|------|
| `name` | ✅ | 技能名，须与 Prompt 中列出的一致 |
| `filename` | ❌ | 技能内的文件，支持多种写法（见下） |

#### 两种模式

| 传参 | 行为 |
|------|------|
| 只传 `name` | 读取该技能 `SKILL.md` **全文** |
| 同时传 `filename` | **只读该附加文件**，不重复加载 `SKILL.md` |

#### filename 的解析顺序

先精确、后模糊，任何一步逃出技能目录都会被拒绝：

| 顺序 | 写法 | 示例 |
|:----:|------|------|
| 1 | 绝对路径 | `D:\office\.agents\skills\demo\references\guide.md` |
| 2 | 相对技能目录 | `references/guide.md` |
| 3 | 相对项目根 | `.agents/skills/demo/references/guide.md` |
| 4 | **只给文件名** | `guide.md` → 在技能目录内递归搜索 |

第 4 种情况：

- **唯一命中** → 直接读取，并返回相对路径（如 `references/guide.md`）
- **多个同名文件** → 不擅自选择，返回候选清单让模型决定：

```
技能「demo」目录中有多个名为「dup.md」的文件，请用 filename 参数指定要读取的路径：
- references/dup.md
- scripts/dup.md
```

#### 安全边界

- 读取范围**严格限制在该技能目录内**，`../` 穿越、绝对路径指向外部、
  读同级其他技能的文件，全部拒绝
- 传了目录时列出其中文件，便于模型自行纠正
- 技能名不存在时列出全部可用技能
- 单文件返回上限 10 万字符，超出会标注截断

**没有技能时不注册此工具**，避免 Prompt 指向不存在的实现。

#### 实测

```json
[调用 loadSkill] {'name': 'fortune-daily'}
  → 返回 SKILL.md 全文

[调用 loadSkill] {'name': 'fortune-daily', 'filename': 'zodiac-index.md'}
  → 技能「fortune-daily」的文件 references/zodiac-index.md：
    # 十二星座快速索引 ...          ← 只给文件名，递归命中
```

模型加载技能正文后**遵守了其中的规则**：

```
用户: 帮我写一份关于下周停电的通知
[调用 loadSkill] {'name': '撰写通知'}
[调用 getDate] {}
→ 通知草稿我来写，但有两项关键信息需要先确认：
  1. 起草人姓名  2. 发布部门
```

技能正文要求「标题必须含部门名称、落款必须有起草人姓名、不清楚时必须先询问」——
模型加载后严格照做。

### createSkill 工具

根据用户的自然语言要求，现场生成一个新技能。

```json
{
  "name": "weekly-report",
  "skillContext": "用于撰写结构化周报\n\n## 工作流程\n1. 收集本周完成事项…"
}
```

| 参数 | 必填 | 说明 |
|------|:----:|------|
| `name` | ✅ | 技能名，自动规范为 kebab-case，并作为目录名 |
| `skillContext` | ✅ | 写入 SKILL.md 的完整内容 |

#### skillContext 怎么拆

约定很简单：**第一行非空文本作为 `description`，其余作为正文**。

```
用于撰写结构化周报          ← description
                            ← 空行
## 工作流程                 ← 以下是正文
1. 收集本周完成事项…
```

如果 `skillContext` 自带完整的 YAML frontmatter，则直接沿用其中的 `description`。

#### 生成结果

```
<项目根>/.agents/skills/weekly-report/SKILL.md
```

```markdown
---
name: weekly-report
description: '用于撰写结构化周报…'
---

## 工作流程
1. 收集本周完成事项…
```

- 目录名与 frontmatter 的 `name` **始终一致**
- `description` 用 YAML 单引号标量，内部单引号自动双写转义
- 生成后会**重新解析一遍**做自校验，不通过则报错

#### 名称规范

| 输入 | 结果 | 说明 |
|------|------|------|
| `PDF Summary` | `pdf-summary` | 转小写、空格转连字符 |
| `doc_writer` | `doc-writer` | 下划线转连字符 |
| `a--b` | `a-b` | 压缩连续连字符 |
| `--x--` | `x` | 去掉首尾连字符 |
| `PDF摘要` | ❌ 拒绝 | 含非英文字符 |

**非英文名被直接拒绝**，而不是裁剪成残名。`PDF摘要` 若裁剪会得到 `pdf`，
丢失关键信息。工具会提示改用 `'pdf-summary'` 这类英文名。

其余约束：最长 64 字符、不许首尾连字符、不许连续连字符、`description` 不许含 `< >`。

#### 拒绝覆盖

目标已存在时立即中止，原文件一字不动：

```
创建失败：技能「doc-writer」已存在（…），为避免覆盖原有内容已中止。
如需修改，请先用 readFile 查看现有 SKILL.md，再用 editFile 更新；或换一个名称。
```

规范化后撞名也算已存在（`PDF Summary` → `pdf-summary` 与已有的同名）。

#### 辅助文件交给 fileops 工具

`createSkill` **只生成 SKILL.md + 目录本身**。需要 `references/`、`scripts/`
等辅助结构时，由模型继续调用已有工具：

```
[createSkill] 创建 weekly-report
[createDir]   创建 .agents/skills/weekly-report/references
[createFile]  创建 references/template.md
```

这样职责单一：一个工具只做一件事，组合由模型完成。

#### 实测

```
用户: 帮我创建一个叫 'weekly-report' 的技能，用于写周报。
      要求：先收集本周完成的事项，按「完成/进行中/风险」三类整理，最后给出下周计划。

[调用 createSkill] 创建成功
→ 已创建技能「weekly-report」

磁盘验证：.agents/skills/weekly-report/SKILL.md 存在，frontmatter 规范
重新扫描：技能 = ['weekly-report']
```

模型生成的正文里还主动写明了「可调用 getDate 确认日期、listDir / readFile 读取素材」，
说明它理解了技能与其他工具的分工。

> 创建成功后新技能会**立即注册到当前会话**，可以直接用
> `loadSkill(name='...')` 加载，不需要重启 wAgent。
> 若原本一个技能都没有，`loadSkill` 也会在此时被动态补注册。

### 在界面里查看

- 顶栏显示 `N 个技能`
- 侧栏「技能 · N」区块列出名称与描述
- `/skills` 命令输出完整清单（含加载失败原因）

### 代码位置

| 文件 | 职责 |
|------|------|
| `core/skills/models.py` | `Skill` / `SkillLoadError` 数据模型 |
| `core/skills/loader.py` | frontmatter 解析、目录扫描、正文与引用文件加载 |
| `core/skills/prompt.py` | 技能清单 → System Prompt 片段 |
| `core/skills/registry.py` | `SkillRegistry` 注册表 |
| `core/tools/skill.py` | `loadSkill` 工具 |
| `main.py` | `load_skills()`：以 cwd 为项目根发起扫描 |

---

## MCP Client

wAgent 可以连接外部 MCP Server，把它们提供的工具当作本地工具一样调用。

### 配置文件

位置：**项目根**（程序启动时的当前工作目录）下的 `.mcp.json`，
不是 wAgent 的源代码目录——这样同一份代码能在不同项目里连不同的 Server。

```json
{
  "mcpServers": {
    "pet-hospital": {
      "type": "streamableHttp",
      "url": "http://127.0.0.1:8090/mcp"
    }
  }
}
```

| 字段 | 说明 |
|------|------|
| `type` | `streamableHttp`（本版本仅支持这个） |
| `url` | MCP 端点地址 |
| `headers` | 可选，附加 HTTP 头（如 `Authorization`） |

### 工作流程

```
启动 → 读 .mcp.json → 逐个连接 → list_tools() → 包装成 Tool → 注册进 ToolRegistry
                                                                    ↓
                                                       与本地工具同一条 Function Calling 通道
```

### 工具命名与冲突

暴露给 LLM 的工具名默认与 MCP Server 中的原名一致。**只有出现跨服务器重名时**
才会加 `服务器名__` 前缀：

```
Server A: list_pets  ──┐
                        ├─→ A__list_pets / B__list_pets
Server B: list_pets  ──┘

Server C: search_docs ──→ search_docs   （无冲突，保持原名）
```

内部维护 `暴露名 → (服务器, 原始工具名)` 映射，调用时据此转发。

若 MCP 工具与**本地工具**重名，保留本地实现，跳过 MCP 版本。

### 结果处理

MCP 返回值有三种形态，统一整理后交给 LLM：

| 情况 | 处理 |
|------|------|
| 只有文本 | 直接返回文本 |
| 有 `structuredContent` | 优先返回 JSON，文本作为补充说明 |
| `isError` 或结构化结果含 `error` | 返回 `MCP 工具调用失败：<原因>` |

### 容错

- **Server 连不上**：记录到 `statuses`，打印到 stderr，**其他工具照常工作**
- **`.mcp.json` 格式错**：记为 issue，启动继续；单个 Server 配置非法只跳过该条
- **调用超时/异常**：返回可读错误文本，Agent 循环不中断
- **没有 `.mcp.json`**：静默跳过，一切如常

连不上时 System Prompt 会明确告知模型：

```
The following MCP servers are currently unreachable:
- pet-hospital (http://127.0.0.1:8090/mcp): 连接被拒绝…
If the user asks for one of those tools, explain that the MCP server is not available…
```

### 前端无关

`core/mcp/` 不依赖任何 UI。`main.py` 负责：

```python
mcp = load_mcp()                     # 以 cwd 为项目根连接
agent = build_agent(mcp=mcp, ...)    # 工具注册进同一个 ToolRegistry
AgentTUI(agent, skills=skills, mcp=mcp).run()
```

TUI 侧栏会显示 `MCP · 1/1` 与每个 Server 的工具数；未连接时显示红点与错误原因。

### 实测

```
[MCP] pet-hospital: 已连接（1 个工具）
工具总数: 16  （15 个本地 + 1 个 MCP）

用户: 帮我查一下当前住院中的宠物有哪些，另外告诉我今天日期

[调用 getDate] {}                       ← 本地工具
  → 周一 2026/11/02  11:23
[调用 list_pets] {'status': '住院中'}    ← MCP 工具
  → { "items": [ { "name": "咪咪", ... } ] }

→ 模型把两者合成一个回答
```

### 技术要点

Agent 循环是**同步生成器**，而 MCP Python SDK 是异步的。`client.py` 在后台线程
跑独立事件循环，用 `run_coroutine_threadsafe` 把异步调用桥接成同步调用，
因此 core 其余部分无需改为 async。

> anyio 会把真实错误包在 `ExceptionGroup` 里，代码递归取出最内层原因，
> 否则用户只会看到「unhandled errors in a TaskGroup」这种无用信息。

---

## 分层设计

### 依赖方向（严格单向）

```
        wAgent.py
            │
            ▼
    ┌──────────────┐
    │     tui/     │  Textual、渲染、输入
    └──────┬───────┘
           │  只用 AgentEvent + build_agent()
           ▼
    ┌──────────────┐
    │    core/     │  Agent、工具、LLM、配置
    └──────────────┘
        （不 import 任何 UI）
```

**core 不知道 UI 存在**：全库无 `print` / `input` / `textual` 引用（已用脚本校验）。

### 分层的三个理由

1. **可测试**：`Agent` 只依赖 `LLMClient` 抽象，测试注入假客户端，无需网络与 Key。
2. **可替换界面**：TUI 只是"订阅者"之一，换 Web 不影响业务逻辑。
3. **职责单一**：LLM 调用、工具执行、消息历史、渲染各自独立。

---

## 关键抽象

### 1. 领域事件（core/events.py）

core 与 UI 的唯一契约。Agent 不返回字符串，而是产出事件流：

| 事件 | 触发时机 |
|------|----------|
| `ROUND_STARTED` | 收到用户输入 |
| `TEXT_DELTA` | 流式文本增量 |
| `TOOL_CALL_STARTED` | 开始执行工具 |
| `TOOL_CALL_FINISHED` | 工具返回结果 |
| `ROUND_FINISHED` | 本轮完成 |
| `ERROR` | 出错 |

### 2. Tool 抽象（core/tools/base.py）

```python
class Tool(ABC):
    name: str
    description: str
    parameters: dict          # JSON Schema
    def run(self, **kwargs) -> str: ...
```

新增工具只需写子类并 `registry.register(MyTool())`，**Agent 引擎零改动**。

### 3. LLMClient 抽象（core/llm/client.py）

```python
class LLMClient(ABC):
    def stream(self, messages, tools) -> Iterator[StreamChunk]: ...
```

换模型厂商只需实现这个接口，不影响 Agent。

---

## 为其他界面预留的扩展点

core 已经就绪，新增前端**不需要改 core**：

```python
from core import build_agent, EventType

agent = build_agent()

# Web（FastAPI + SSE）示例
@app.post("/chat")
async def chat(prompt: str):
    async def gen():
        for ev in agent.stream_reply(prompt):
            yield f"data: {json.dumps({'type': ev.type.value, **ev.payload})}\n\n"
    return StreamingResponse(gen(), media_type="text/event-stream")

# Desktop（PySide/Tkinter）同理：事件循环里调用 stream_reply 即可
```

**注意**：`stream_reply` 是同步生成器，Web/异步场景建议用 `run_in_executor` 或后续加 `astream_reply` 的异步版本。

---

## 相对原 chat.py 的改进

| 项 | 原实现 | 现实现 |
|----|--------|--------|
| 结构 | 单文件 211 行，逻辑与 UI 混杂 | core 7 模块 / tui 4 模块 |
| 输出 | `print` + `time.sleep` 打字机 | 事件流，由 UI 决定呈现 |
| 测试 | 无 | 17 项自动化测试 |
| 工具扩展 | 改 `TOOL_HANDLERS` 字典 | 注册 Tool 子类 |
| 密钥泄露 | 原代码无防护 | `LLMSettings.__repr__` 脱敏 |
| 依赖注入 | 硬编码 `D:\openai` 路径 | `build_agent(client=...)` 可注入 |
| 异常回滚 | 有 | 保留（`test_rollback_on_error` 覆盖） |

---

## 已知事项

1. **`config.ini` 里的 Key 已失效**（实测 401）。使用前请换成有效的 DeepSeek Key。
2. 原 `D:\openai` 路径注入已移除，改为标准 `pip install openai`。
3. `chat.py` / `chat_leapyear.py` / `chat_fileops.py` 保持原样未改动，本次改造只针对新架构。
