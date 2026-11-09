# 上游依赖说明（务必先读）

本项目由**三个可独立运行的模块**组成，其中两个依赖外部前置条件。
这些依赖**不随仓库分发**，需要按下面的说明准备。

| 模块 | 是否自带可运行内容 | 前置条件 |
|------|:------------------:|----------|
| `Agent/wAgent` | ✅ 完全自带 | 只需 Python 依赖与 API Key |
| `AnythingLLMWebPage` | ✅ 完全自带 | 需要一个运行中的 AnythingLLM |
| `AnythingLLMMCP` | ✅ 完全自带 | 同上（含 API Key） |
| `PetHospitalMCP` | ⚠️ 需要二进制 | 需要课程提供的 `pethospital.exe` |

---

## 一、宠物医院服务端（`PetHospitalServer/`）

### 为什么不在仓库里

`pethospital.exe` 约 6.5 MB，是**课程提供的第三方可执行文件**，不是本项目的源代码。
把它放进 Git 仓库会让仓库体积膨胀，且无法通过代码审查判断其内容，
因此通过 `.gitignore` 排除。

### 如何获取

按课程要求，向指导教师（谢心）获取 `pethospital.exe`，然后放到：

```
PetHospitalServer/pethospital.exe
```

### 数据文件

服务端会在首次启动时自动创建 `PetHospitalServer/data/pet.db`。
仓库同样不包含该文件（`.gitignore` 中排除），因为它是运行时产生的数据。

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

### 没有二进制时能做什么

`PetHospitalMCP` 本身仍然可以启动、可以自检协议、可以被 MCP 客户端连接并列出工具。
只是调用 `list_pets` 时会返回明确的结构化错误：

```json
{"error": {"code": "BACKEND_UNAVAILABLE", "message": "无法连接 http://127.0.0.1:8080（已重试 3 次），请先启动 pethospital.exe"}}
```

这个错误是可诊断的，不会静默失败。

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
