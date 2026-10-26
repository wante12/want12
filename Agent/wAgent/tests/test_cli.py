"""RunCli 工具测试：使用真实的轻量命令（python 本身），不访问网络。

关键验证点：
- 参数以列表传递、shell=False
- stdout / stderr / 退出码三者都回传
- 超时与超长输出被正确处理
- 命令不存在等异常转成文本而非抛出
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from core.config import CliSettings  # noqa: E402
from core.tools.base import ToolRegistry  # noqa: E402
from core.tools.cli import RunCliTool  # noqa: E402

PY = sys.executable


def py(code: str) -> tuple[str, list[str]]:
    """构造一个执行 python 代码片段的 (command, args)。"""
    return PY, ["-c", code]


# ---------------------------------------------------------------- 正常路径
def test_success_returns_stdout_and_exit_code():
    out = RunCliTool().run(*py("print('hello world')"))
    assert "退出码：0" in out
    assert "hello world" in out
    assert "成功" in out


def test_nonzero_exit_and_stderr():
    cmd, args = py("import sys; sys.stderr.write('bad thing'); sys.exit(3)")
    out = RunCliTool().run(cmd, args)

    assert "退出码：3" in out
    assert "失败" in out
    assert "bad thing" in out
    assert "--- stderr ---" in out


def test_empty_stdout_is_marked():
    out = RunCliTool().run(*py("import sys; sys.exit(0)"))
    assert "(无输出)" in out


def test_chinese_output_is_decoded():
    """中文 Windows 输出多为 GBK/UTF-8，需正确解码不出现乱码。"""
    out = RunCliTool().run(*py("print('中文测试输出')"))
    assert "中文测试输出" in out


def test_multiple_args_preserved():
    args = ["-c", "import sys; print('|'.join(sys.argv[1:]))", "a b", "c;d", "$HOME"]
    out = RunCliTool().run(PY, args)
    # 含空格、分号、$ 的参数必须原样到达，不被 shell 解释
    assert "a b" in out and "c;d" in out and "$HOME" in out


# ---------------------------------------------------------------- 安全
def test_shell_not_used(monkeypatch):
    """断言调用 subprocess 时 shell=False 且 argv 为列表。"""
    captured: dict = {}

    class Fake:
        returncode = 0
        stdout = b"ok"
        stderr = b""

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        return Fake()

    monkeypatch.setattr("subprocess.run", fake_run)
    RunCliTool().run("echo", ["hi"])

    assert isinstance(captured["argv"], list)
    assert captured["kwargs"].get("shell") is False


def test_shell_metachar_not_interpreted():
    """含 shell 元字符的参数应作为普通字符串传入，不触发二次解释。"""
    marker = "x; echo INJECTED"
    out = RunCliTool().run(PY, ["-c", "import sys; print(sys.argv[1])", marker])
    # 只检查 stdout 段：若被 shell 解释，这里会多出一行 "INJECTED"
    stdout_part = out.split("--- stdout ---", 1)[-1]
    assert stdout_part.strip() == marker


def test_args_none_defaults_to_empty():
    """args 传 None 时应视作空列表，不带任何参数执行。"""
    import shutil

    if not shutil.which("whoami"):
        pytest.skip("当前系统没有 whoami，跳过")

    # whoami 不带参数即可退出，正好验证 args=None 的路径
    out = RunCliTool().run("whoami", None)
    assert "退出码：0" in out


# ---------------------------------------------------------------- 参数校验
def test_empty_command():
    assert "command 不能为空" in RunCliTool().run("")


def test_args_must_be_list():
    out = RunCliTool().run("echo", "not-a-list")
    assert "必须是字符串列表" in out


# ---------------------------------------------------------------- 异常
def test_command_not_found():
    out = RunCliTool().run("definitely_no_such_cmd_xyz_123")
    assert "找不到程序" in out


def test_timeout_marks_partial_output():
    out = RunCliTool(CliSettings(timeout=2.0)).run(
        *py("import time,sys; print('begin'); sys.stdout.flush(); time.sleep(8)")
    )
    assert "执行超时" in out
    assert "begin" in out          # 超时前的输出应保留
    assert "可能不完整" in out


# ---------------------------------------------------------------- 截断
def test_long_output_truncated_with_marker():
    out = RunCliTool(CliSettings(max_output_chars=100)).run(
        *py("print('A'*200); print('TAIL')")
    )
    assert "省略" in out
    assert "已截断" in out
    assert "TAIL" in out          # 尾部保留


def test_short_output_not_truncated():
    out = RunCliTool(CliSettings(max_output_chars=4000)).run(*py("print('short')"))
    assert "省略" not in out


# ---------------------------------------------------------------- 集成
def test_never_raises_through_registry(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("意外崩溃")

    monkeypatch.setattr("subprocess.run", boom)
    reg = ToolRegistry()
    reg.register(RunCliTool())
    out = reg.execute("RunCli", '{"command":"x"}')
    assert "执行失败" in out


def test_schema_shape():
    schema = RunCliTool().to_schema()["function"]
    assert schema["name"] == "RunCli"
    assert schema["parameters"]["required"] == ["command"]
    assert schema["parameters"]["properties"]["args"]["type"] == "array"
    assert schema["parameters"]["additionalProperties"] is False
