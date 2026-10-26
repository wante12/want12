"""fetchWeb 工具测试：全部离线，不发起真实网络请求。

通过替换 subprocess.run 模拟 curl 的各种返回。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from core.config import FetchSettings  # noqa: E402
from core.tools.base import ToolRegistry  # noqa: E402
from core.tools.fetch import FetchWebTool  # noqa: E402

STATUS = "\n__FETCHWEB_STATUS__:"

ARTICLE_HTML = """<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<title>测试标题 - 示例网站</title>
</head><body>
<header><nav><a href="/">首页</a> | <a href="/sports">体育</a> | <a href="/news">新闻</a></nav></header>
<main><article>
<h1>测试标题</h1>
<p>这是第一段正文内容，用于验证提取效果。这一句足够长，可以帮助算法判断这是正文而不是导航。</p>
<h2>小标题</h2>
<p>第二段内容，继续补充正文长度，让提取器更容易识别主要内容区域。</p>
<ul><li>列表项一</li><li>列表项二</li></ul>
<p>段落中包含<a href="https://example.com/link">一个链接</a>，用于测试链接保留。</p>
<table><thead><tr><th>列A</th><th>列B</th></tr></thead>
<tbody><tr><td>1</td><td>2</td></tr></tbody></table>
<p>最后一段正文，再次补充内容长度以确保提取成功，这段话也很长很完整。</p>
</article></main>
<footer><p>版权所有 © 2026 示例网站 京ICP备00000000号</p></footer>
</body></html>
"""


class FakeResult:
    def __init__(self, stdout: bytes, stderr: bytes = b"", returncode: int = 0) -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def patch_curl(monkeypatch, stdout: bytes, stderr: bytes = b"", returncode: int = 0) -> list:
    """替换 subprocess.run，记录调用参数。"""
    calls: list = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return FakeResult(stdout, stderr, returncode)

    monkeypatch.setattr(subprocess, "run", fake_run)
    return calls


def html_with_status(html: str, status: int = 200) -> bytes:
    return (html + STATUS + str(status)).encode("utf-8")


# ---------------------------------------------------------------- 正常路径
def test_fetch_extracts_article(monkeypatch):
    patch_curl(monkeypatch, html_with_status(ARTICLE_HTML))
    out = FetchWebTool().run("https://example.com/article")

    assert "https://example.com/article" in out
    assert "测试标题" in out
    assert "第一段正文内容" in out
    # 导航与页脚应被剔除
    assert "体育" not in out
    assert "版权所有" not in out


def test_fetch_preserves_structure(monkeypatch):
    patch_curl(monkeypatch, html_with_status(ARTICLE_HTML))
    out = FetchWebTool().run("https://example.com/article")

    assert "#" in out                                  # 标题层级
    assert "](https://example.com/link)" in out        # 链接
    assert "|" in out                                  # 表格
    assert "列表项一" in out                           # 列表内容


def test_fetch_truncates_long_content(monkeypatch):
    long_html = "<html><body><article>" + "<p>" + ("内容" * 20000) + "</p></article></body></html>"
    patch_curl(monkeypatch, html_with_status(long_html))
    out = FetchWebTool(FetchSettings(max_chars=500)).run("https://example.com/long")

    assert len(out) < 1200
    assert "已截断" in out


# ---------------------------------------------------------------- 参数校验
def test_empty_url():
    out = FetchWebTool().run("")
    assert "不能为空" in out


@pytest.mark.parametrize("bad", ["www.example.com", "ftp://x.com", "file:///etc/passwd"])
def test_invalid_scheme_rejected(bad):
    out = FetchWebTool().run(bad)
    assert "http://" in out and "https://" in out


# ---------------------------------------------------------------- 安全
def test_uses_argument_list_not_shell(monkeypatch):
    calls = patch_curl(monkeypatch, html_with_status(ARTICLE_HTML))
    FetchWebTool().run("https://example.com/article")

    argv, kwargs = calls[0]
    assert isinstance(argv, list)                    # 参数列表
    assert not kwargs.get("shell")                   # 绝不使用 shell=True
    assert argv[0] == "curl"
    assert "https://example.com/article" in argv


def test_url_with_shell_metachar_is_single_arg(monkeypatch):
    """即使 url 含 shell 元字符，也只是列表中的一个元素。"""
    calls = patch_curl(monkeypatch, html_with_status(ARTICLE_HTML))
    malicious = "https://example.com/x;rm -rf /"
    FetchWebTool().run(malicious)

    argv, kwargs = calls[0]
    assert argv[-1] == malicious
    assert not kwargs.get("shell")


# ---------------------------------------------------------------- 网络异常
def test_curl_not_found(monkeypatch):
    def boom(*a, **k):
        raise FileNotFoundError()

    monkeypatch.setattr(subprocess, "run", boom)
    out = FetchWebTool().run("https://example.com")
    assert "找不到 curl" in out


def test_subprocess_timeout(monkeypatch):
    def boom(*a, **k):
        raise subprocess.TimeoutExpired("curl", 20)

    monkeypatch.setattr(subprocess, "run", boom)
    out = FetchWebTool().run("https://example.com")
    assert "超时" in out


@pytest.mark.parametrize(
    "code,expect",
    [
        (6, "无法解析域名"),
        (7, "无法连接"),
        (28, "请求超时"),
        (35, "SSL"),
    ],
)
def test_curl_error_codes(monkeypatch, code, expect):
    patch_curl(monkeypatch, b"", b"curl: error", returncode=code)
    out = FetchWebTool().run("https://example.com")
    assert expect in out
    assert str(code) in out


def test_http_404(monkeypatch):
    patch_curl(monkeypatch, html_with_status("<html>404</html>", 404))
    out = FetchWebTool().run("https://example.com/nope")
    assert "404" in out
    assert "未找到" in out


def test_empty_response(monkeypatch):
    patch_curl(monkeypatch, html_with_status("", 200))
    out = FetchWebTool().run("https://example.com")
    assert "内容为空" in out


# ---------------------------------------------------------------- 提取失败
def test_no_extractable_content(monkeypatch):
    patch_curl(monkeypatch, html_with_status("<html><body></body></html>", 200))
    out = FetchWebTool().run("https://example.com/blank")
    assert "无法从中提取正文" in out


def test_missing_trafilatura(monkeypatch):
    patch_curl(monkeypatch, html_with_status(ARTICLE_HTML))
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name == "trafilatura":
            raise ImportError("no trafilatura")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    out = FetchWebTool().run("https://example.com/article")
    assert "trafilatura" in out


# ---------------------------------------------------------------- 集成
def test_never_raises_through_registry(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("意外崩溃")

    monkeypatch.setattr(subprocess, "run", boom)
    reg = ToolRegistry()
    reg.register(FetchWebTool())
    out = reg.execute("fetchWeb", '{"url":"https://example.com"}')
    assert "抓取失败" in out


def test_schema_shape():
    schema = FetchWebTool().to_schema()["function"]
    assert schema["name"] == "fetchWeb"
    assert schema["parameters"]["required"] == ["url"]
    assert schema["parameters"]["additionalProperties"] is False
