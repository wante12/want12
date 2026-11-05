"""上下文用量显示控件。

醒目位置（顶栏下方）显示：上下文长度 / 模型窗口 / 占用百分比
超过 70% 变黄并提示 /compact；压缩中提示正在压缩。

实现要点：
用 Static 并**始终保证有文本内容**。Static 的 render() 在无内容时返回 None，
会使 Textual 计算尺寸时抛 AttributeError，因此初始文本不能为空。
配色通过 CSS class 表达，不依赖 rich markup，兼容 NO_COLOR 环境。
"""

from __future__ import annotations

from textual.widgets import Static


class ContextMeter(Static):
    """一行式上下文计量条。"""

    def __init__(self, **kwargs) -> None:
        # 初始必须有文本，否则 Static.render() 返回 None 会让布局计算崩溃
        super().__init__("上下文 -- / --", id="ctx-meter", **kwargs)
        self._usage = None
        self._compacting = False
        self.add_class("idle")

    def update_usage(self, usage, compacting: bool = False) -> None:
        self._usage = usage
        self._compacting = compacting
        self._refresh_text()

    def _refresh_text(self) -> None:
        if self._compacting:
            self._set_state("busy")
            self.update("⟳ 正在压缩上下文…（工具已禁用）")
            return

        if self._usage is None:
            self._set_state("idle")
            self.update("上下文 -- / --")
            return

        used_k = self._usage.used / 1024
        window_k = self._usage.window / 1024
        percent = self._usage.percent
        note = "（默认）" if self._usage.window_is_default else ""
        est = " · 估算" if not self._usage.measured_by_api else ""

        if percent >= 70:
            self._set_state("warn" if percent < 85 else "danger")
            self.update(
                f"上下文 {used_k:.1f}k / {window_k:.0f}k{note} · {percent:.0f}%"
                "  ⚠ 已达 70%，请执行 /compact"
            )
        else:
            self._set_state("ok")
            self.update(
                f"上下文 {used_k:.1f}k / {window_k:.0f}k{note} · {percent:.0f}%{est}"
            )

    def _set_state(self, state: str) -> None:
        for name in ("ok", "warn", "danger", "busy", "idle"):
            try:
                self.set_class(name == state, name)
            except Exception:  # noqa: BLE001 界面拆卸时忽略
                pass

    @property
    def needs_attention(self) -> bool:
        return bool(self._usage and self._usage.needs_compact)

    def render(self):
        """确保永远返回非 None，避免 Textual 计算尺寸时崩溃。"""
        visual = super().render()
        return visual if visual is not None else ""
