"""验证 MCP 服务两套协议都能正常工作。

用法（先启动 pethospital.exe 和 server.py）：
    python check.py
"""

import json
import sys

import httpx

URL = "http://127.0.0.1:8091/mcp"
MODERN = "2026-07-28"


def post(body: dict, headers: dict) -> dict:
    r = httpx.post(URL, json=body, headers=headers, timeout=30)
    if r.status_code >= 400:
        sys.exit(f"HTTP {r.status_code}: {r.text[:300]}")
    return r.json()


def check_legacy() -> None:
    """旧协议：可能带 initialize 握手，也可能直接调用。"""
    h = {"Accept": "application/json, text/event-stream"}
    init = post({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                 "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                            "clientInfo": {"name": "check", "version": "1"}}}, h)
    print("旧版 initialize ->", init["result"]["protocolVersion"])

    call = post({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                 "params": {"name": "list_pets", "arguments": {"status": "住院中"}}}, h)
    d = call["result"]["structuredContent"]
    assert not call["result"]["isError"], call
    print("旧版 tools/call -> total:", d["total"], "| 例:", d["items"][0]["name"])


def check_modern() -> None:
    """新协议：单次 POST，无握手；params._meta 携带信封字段。"""
    meta = {"io.modelcontextprotocol/protocolVersion": MODERN,
            "io.modelcontextprotocol/clientCapabilities": {}}

    listed = post({"jsonrpc": "2.0", "id": 3, "method": "tools/list",
                   "params": {"_meta": meta}},
                  {"Accept": "application/json", "MCP-Protocol-Version": MODERN,
                   "Mcp-Method": "tools/list"})
    names = [t["name"] for t in listed["result"]["tools"]]
    print("新版 tools/list ->", names)
    assert names == ["list_pets"]

    called = post({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                   "params": {"name": "list_pets",
                              "arguments": {"species": "猫", "pageSize": 2},
                              "_meta": meta}},
                  {"Accept": "application/json", "MCP-Protocol-Version": MODERN,
                   "Mcp-Method": "tools/call", "Mcp-Name": "list_pets"})
    d = called["result"]["structuredContent"]
    assert not called["result"]["isError"], called
    print("新版 tools/call -> total:", d["total"], "| 例:", d["items"][0]["name"])


if __name__ == "__main__":
    check_legacy()
    check_modern()
    print("\n两套协议均通过 ✓")
