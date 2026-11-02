# BaziMCP

本地托管 [bazi-mcp](https://modelscope.cn/mcp/servers/@cantian-ai/Bazi-MCP)（Cantian AI 的八字 MCP），
以 **Streamable HTTP** 方式运行，供 wAgent 通过 `.mcp.json` 接入。

## 为什么需要这个目录

原始包 `bazi-mcp` 默认是 **stdio** 传输（`npx bazi-mcp`），而 wAgent 的 MCP 客户端
本版本只支持 Streamable HTTP。该包自带 `dist/httpServer.js`，可用 HTTP 模式启动，
本目录把它固定安装并提供启动脚本，避免每次从临时目录运行。

## 服务信息

| 项 | 值 |
|----|-----|
| 端口 | `8095`（由 `PORT` 环境变量控制） |
| MCP 端点 | `http://127.0.0.1:8095/mcp` |
| 传输 | Streamable HTTP（无状态，`sessionIdGenerator: undefined`） |
| 协议 | 协商为 `2025-11-25`（SDK 1.x） |

## 提供的工具

| 工具 | 说明 |
|------|------|
| `getBaziDetail` | 按公历/农历时间 + 性别算八字。`solarDatetime` 与 `lunarDatetime` 二选一 |
| `getSolarTimes` | 从八字反推可能的公历时间列表 |
| `getChineseCalendar` | 查询指定公历时间的黄历信息 |

## 启动

在 `D:\LLM-Course` 下双击：

```
start-mcp-bazi.bat
```

或手动：

```powershell
cd D:\LLM-Course\BaziMCP
$env:PORT = "8095"
node node_modules\bazi-mcp\dist\httpServer.js
```

首次运行会自动 `npm install`（脚本已处理）。

## 依赖

- **Node.js 22+**（本机 v24.21.0）
- `bazi-mcp@0.1.0`

## 配置（wAgent 侧）

在启动目录的 `.mcp.json` 里：

```json
{
  "mcpServers": {
    "bazi": {
      "type": "streamableHttp",
      "url": "http://127.0.0.1:8095/mcp"
    }
  }
}
```

## 验证

```powershell
# 健康检查（HTTP 模式下没有 /health，用 tools/list 验证）
Invoke-WebRequest http://127.0.0.1:8095/mcp -Method Post -UseBasicParsing `
  -Body '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' `
  -ContentType 'application/json' -Headers @{Accept='application/json, text/event-stream'}
```

实测调用结果：

```
getBaziDetail(1990-05-20 14:30, 男)
→ 八字：庚午 辛巳 乙酉 癸未 | 生肖：马 | 日主：乙
   年柱：庚午（正官 / 藏干丁己）
   月柱：辛巳（七杀 / 藏干丙庚戊）
   日柱：乙酉
   时柱：癸未（偏印 / 藏干己丁乙）
```

## 注意

这是**命理娱乐工具**，输出仅供参考试玩，不构成任何人生决策依据。
