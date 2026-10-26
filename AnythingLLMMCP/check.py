"""验证 AnythingLLM MCP 服务两套协议。用法：python check.py"""

import sys

import httpx

URL = "http://127.0.0.1:8093/mcp"
MODERN = "2026-07-28"


def post(body, headers):
    r = httpx.post(URL, json=body, headers=headers, timeout=60)
    if r.status_code >= 400:
        sys.exit(f"HTTP {r.status_code}: {r.text[:300]}")
    return r.json()


def show(tag, result):
    if result.get("isError"):
        print(f"{tag} -> 工具返回错误:", result["content"][0]["text"][:300])
        return
    sc = result.get("structuredContent") or {}
    ws = sc.get("workspace", {})
    print(f"{tag} -> 工作区: {ws.get('name')} | 文件数: {sc.get('count')}")
    for f in (sc.get("files") or [])[:5]:
        print(f"    - {f.get('title')}")


# 旧协议
h = {"Accept": "application/json, text/event-stream"}
post({"jsonrpc": "2.0", "id": 1, "method": "initialize",
      "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                 "clientInfo": {"name": "check", "version": "1"}}}, h)
show("旧版", post({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                 "params": {"name": "list_workspace_files", "arguments": {}}}, h)["result"])

# 新协议
meta = {"io.modelcontextprotocol/protocolVersion": MODERN,
        "io.modelcontextprotocol/clientCapabilities": {}}
listed = post({"jsonrpc": "2.0", "id": 3, "method": "tools/list", "params": {"_meta": meta}},
              {"Accept": "application/json", "MCP-Protocol-Version": MODERN,
               "Mcp-Method": "tools/list"})
print("新版 tools/list ->", [t["name"] for t in listed["result"]["tools"]])
show("新版", post({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                 "params": {"name": "list_workspace_files",
                            "arguments": {"preview_chars": 80}, "_meta": meta}},
                {"Accept": "application/json", "MCP-Protocol-Version": MODERN,
                 "Mcp-Method": "tools/call", "Mcp-Name": "list_workspace_files"})["result"])

print("\n两套协议均通过 ✓")
