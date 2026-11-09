# 上游依赖说明（务必先读）

本项目由**三个可独立运行的模块**组成。宠物医院服务端的可执行文件**已随仓库分发**，
其余外部服务（AnythingLLM）需自行准备。

| 模块 | 是否自带可运行内容 | 前置条件 |
|------|:------------------:|----------|
| `Agent/wAgent` | ✅ 完全自带 | 只需 Python 依赖与 API Key |
| `AnythingLLMWebPage` | ✅ 完全自带 | 需要一个运行中的 AnythingLLM |
| `AnythingLLMMCP` | ✅ 完全自带 | 同上（含 API Key） |
| `PetHospitalMCP` | ✅ 完全自带 | 服务端二进制已随仓库分发 |

---

## 一、宠物医院服务端（`PetHospitalServer/`）

### 交付方式

`pethospital.exe` **已随仓库分发**，克隆后即可直接运行，无需额外获取。

| 项 | 值 |
|----|-----|
| 文件 | `PetHospitalServer/pethospital.exe` |
| 大小 | 6.47 MB |
| 来源 | 课程提供（指导教师：谢心） |
| SHA256 | `1CC99DB34E2CBB133897644BCAE298ABD53DFBE6315703601D1F57D9D988803E` |

克隆后校验完整性：

```powershell
Get-FileHash PetHospitalServer\pethospital.exe -Algorithm SHA256
# 应与上表一致
```

> 该文件仅用于课程学习与本地演示，版权归课程提供方所有，请勿另行分发。

### 数据文件

服务端首次启动时会自动创建 `PetHospitalServer/data/pet.db`。
**该文件不入库**（`.gitignore` 中排除），因为它是运行时产生的业务数据，
每次运行都可能变化，且体积约 2.4 MB。

首次启动后会自动初始化演示数据。

### 验证服务端可用

```powershell
cd PetHospitalServer
.\pethospital.exe
```

看到监听 `127.0.0.1:8080` 后，浏览器打开 <http://127.0.0.1:8080/> 应能看到网页界面，
或直接检查健康接口：

```powershell
Invoke-WebRequest http://127.0.0.1:8080/health -UseBasicParsing
```

返回含 `"status":"healthy"` 的 JSON 即正常。

### 若二进制无法运行

某些环境（如非 Windows 系统、被杀毒软件拦截）可能无法运行该 exe。
此时 `PetHospitalMCP` 仍可启动、可自检协议、可被 MCP 客户端连接并列出工具，
只是调用 `list_pets` 会返回明确的结构化错误：

```json
{"error": {"code": "BACKEND_UNAVAILABLE", "message": "无法连接 http://127.0.0.1:8080（已重试 3 次），请先启动 pethospital.exe"}}
```

这个错误可诊断，不会静默失败。

---

## 二、AnythingLLM（`AnythingLLMMCP/` 与 `AnythingLLMWebPage/`）

### 需要什么

一个运行中的 AnythingLLM 实例，默认地址 `http://localhost:3001`。

### 配置步骤

1. 启动 AnythingLLM，创建一个工作区（两个模块都只操作**第一个**工作区）
2. 打开「设置 → 工具 → 开发者 API」，创建一个 API Key
3. 把 Key 交给对应的模块：

| 模块 | 配置方式 |
|------|----------|
| `AnythingLLMMCP` | 环境变量 `ANYTHINGLLM_API_KEY` |
| `AnythingLLMWebPage` | 在网页输入框里粘贴 |

### 关于文档解析服务

上传文档需要 AnythingLLM 的 **collector 服务（端口 8888）**处于运行状态。
若网页提示 `Document processing API is not online`，请先确认该服务已启动。

---

## 三、第三方 MCP 服务（可选）

`BaziMCP/` 封装了一个第三方的八字测算 MCP 服务，属于**演示性质的可选模块**，
不影响前两个主任务的运行。参见 `BaziMCP/README.md`。

---

## 四、快速自检清单

在没有任何外部服务的情况下，以下内容应当**全部可用**：

```powershell
# 1. wAgent 单元测试
cd Agent\wAgent
python -m pytest -q
# 预期：全部通过（需要 MCP 服务的用例会自动跳过）

# 2. wAgent 启动
cd D:\office          # 或任意项目目录
python D:\LLM-Course\Agent\wAgent\main.py
# 预期：进入界面，侧栏 MCP 显示 0/0 或已配置但未连接

# 3. 宠物医院 MCP 自检（不依赖 REST 后端是否存活）
cd PetHospitalMCP
.venv\Scripts\python.exe check.py
# 预期：协议层自检通过；数据调用部分会报告后端不可用
```

启动外部服务后，再按顶层 `README.md` 的「一键启动」章节操作。
