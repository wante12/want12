"""searchWeb 工具测试：全部离线，不发真实请求。

通过替换 urllib.request.urlopen 模拟各种响应与异常。
"""

from __future__ import annotations

import io
import json
import sys
import urllib.error
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from core.config import SearchSettings  # noqa: E402
from core.tools.base import ToolRegistry  # noqa: E402
from core.tools.search import SearchWebTool  # noqa: E402

KEY = "test-key"


def make_tool(**kw) -> SearchWebTool:
    return SearchWebTool(SearchSettings(api_key=kw.pop("api_key", KEY), **kw))


def fake_response(payload: dict) -> io.BytesIO:
    """构造一个可被 urlopen 上下文管理器使用的假响应。"""

    class _Resp(io.BytesIO):
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    return _Resp(json.dumps(payload, ensure_ascii=False).encode("utf-8"))


SAMPLE = {
    "request_id": "r1",
    "references": [
        {
            "title": "标题一",
            "url": "https://example.com/a",
            "snippet": "摘要一",
            "website": "站点一",
            "date": "2026-01-01",
        },
        {
            "title": "标题二",
            "url": "https://example.com/b",
            "content": "内容二",
            "website": "站点二",
        },
    ],
}


# ---------------------------------------------------------------- 正常路径
def test_search_formats_summary_and_sources(monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: fake_response(SAMPLE))
    out = make_tool().run("测试查询")

    assert "测试查询" in out
    assert "摘要一" in out
    assert "内容二" in out          # 没 snippet 时回退 content
    assert "参考来源" in out
    assert "https://example.com/a" in out
    assert "https://example.com/b" in out


def test_search_respects_top_k(monkeypatch):
    many = {"references": [{"title": f"t{i}", "url": f"https://e.com/{i}"} for i in range(20)]}
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: fake_response(many))
    out = make_tool(top_k=3).run("q")

    assert out.count("https://e.com/") == 3


def test_search_handles_empty_results(monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: fake_response({"references": []}))
    out = make_tool().run("没有结果的查询")
    assert "未找到" in out


def test_search_truncates_long_snippet(monkeypatch):
    long_text = {"references": [{"title": "t", "url": "u", "snippet": "长" * 1000}]}
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: fake_response(long_text))
    out = make_tool().run("q")
    assert "…" in out
    assert len(out) < 900


# ---------------------------------------------------------------- 配置缺失
def test_missing_api_key_returns_hint():
    out = SearchWebTool(SearchSettings()).run("q")
    assert "未配置" in out
    assert "baidu_qianfan_api_key" in out


def test_empty_query_rejected():
    out = make_tool().run("   ")
    assert "不能为空" in out


# ---------------------------------------------------------------- 网络异常
def test_network_error(monkeypatch):
    def boom(*a, **k):
        raise urllib.error.URLError("getaddrinfo failed")

    monkeypatch.setattr("urllib.request.urlopen", boom)
    out = make_tool().run("q")
    assert "网络连接失败" in out


def test_timeout(monkeypatch):
    def boom(*a, **k):
        raise TimeoutError()

    monkeypatch.setattr("urllib.request.urlopen", boom)
    out = make_tool().run("q")
    assert "超时" in out


# ---------------------------------------------------------------- HTTP 错误
@pytest.mark.parametrize(
    "code,expect",
    [
        (401, "API Key 无效"),
        (403, "无权访问"),
        (429, "频繁"),
        (500, "服务端内部错误"),
    ],
)
def test_http_errors_are_translated(monkeypatch, code, expect):
    def boom(*a, **k):
        raise urllib.error.HTTPError(
            "http://x", code, "err", {}, io.BytesIO(b'{"message":"detail"}')
        )

    monkeypatch.setattr("urllib.request.urlopen", boom)
    out = make_tool().run("q")
    assert expect in out
    assert f"HTTP {code}" in out


# ---------------------------------------------------------------- 响应异常
def test_invalid_json(monkeypatch):
    class _R(io.BytesIO):
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: _R(b"not json"))
    out = make_tool().run("q")
    assert "不是合法 JSON" in out


def test_business_error_code(monkeypatch):
    payload = {"code": 216003, "message": "权限不足"}
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: fake_response(payload))
    out = make_tool().run("q")
    assert "216003" in out
    assert "权限不足" in out


# ---------------------------------------------------------------- 集成
def test_tool_never_raises_through_registry(monkeypatch):
    """工具异常必须被转成文本，不能穿透到 Agent 循环。"""
    def boom(*a, **k):
        raise RuntimeError("意外崩溃")

    monkeypatch.setattr("urllib.request.urlopen", boom)
    reg = ToolRegistry()
    reg.register(make_tool())
    out = reg.execute("searchWeb", '{"query":"q"}')
    assert "搜索失败" in out


def test_schema_shape():
    schema = SearchWebTool(SearchSettings()).to_schema()["function"]
    assert schema["name"] == "searchWeb"
    assert schema["parameters"]["required"] == ["query"]
    assert schema["parameters"]["additionalProperties"] is False
