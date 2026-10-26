# 第三个开发任务 · AnythingLLMWebPage

一个网页，给 AnythingLLM **第一个工作区**上传文档并完成向量化嵌入。

## 文件

```
AnythingLLMWebPage\
├── index.html    ← 单文件网页，无依赖、无构建
└── README.md
```

## 使用

1. 确保 AnythingLLM 后端在跑（`http://localhost:3001`）
2. 双击打开 `index.html`
3. 填 **API Key**（「设置 → 工具 → 开发者 API」创建）
4. 工作区留空 = **自动用第一个工作区**（按需求，不需要选）
5. 拖入文件或点击选择 → 点「上传并嵌入」

每个文件单独显示成功/失败，失败不影响其他文件。

## 用到的接口

| 步骤 | 接口 |
|------|------|
| 取第一个工作区 | `GET /v1/workspaces` → `workspaces[0].slug` |
| 上传 | `POST /v1/document/upload`（multipart，字段名 `file`） |
| 嵌入 | `POST /v1/workspace/{slug}/update-embeddings`，body `{"adds":[location]}` |

鉴权：`Authorization: Bearer <API Key>`。

> 上传时**不要**手动设 `Content-Type`，让浏览器自动带 multipart `boundary`。

## 实测

用 `webpage_upload_test.txt` 走完整链路：

- 上传 → `HTTP 200`，返回 `location: custom-documents/webpage_upload_test.txt-<uuid>.json`
- 嵌入 → `HTTP 200`
- 工作区文档数 4 → 5 ✓

> 注意：`update-embeddings` 成功时返回的 `adds` 可能是空数组（`added: 0`），
> **不要用它判断是否成功**，要以工作区文档列表为准。

## 常见问题

| 现象 | 原因 / 处理 |
|------|-------------|
| `Document processing API is not online` | **文档解析服务（collector，端口 8888）没启动**，AnythingLLM 需要它是运行状态 |
| `401` / `403` | API Key 不对 |
| 上传成功但工作区里没有 | 嵌入那步失败，看日志；或工作区 slug 取错 |
| 中文乱码 | 文件用 UTF-8 保存 |
