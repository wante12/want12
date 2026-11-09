"""pytest 全局配置。

关键作用：**每个测试用例前后重置文件系统沙箱**。

`build_fs_tools()` 会把 allowed_roots 写入 ContextVar，
若不在用例之间清理，前一个用例设置的沙箱会泄漏到后一个用例，
导致「单独跑通过、一起跑失败」这类难以定位的问题。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

BASE = Path(__file__).resolve().parent.parent
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

from core.tools.filesystem import reset_sandbox  # noqa: E402


@pytest.fixture(autouse=True)
def _clean_sandbox():
    """每个用例前后都恢复默认（不限制）状态。"""
    reset_sandbox()
    yield
    reset_sandbox()
