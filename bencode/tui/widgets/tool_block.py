"""工具调用折叠卡片组件

每次工具调用在消息流中渲染为一张折叠卡片：
- 默认折叠，摘要行显示 图标 + 工具名 + 状态（+ 耗时）
- 展开可查看完整参数与执行结果
- 状态：执行中 / 成功 / 失败 / 被拒绝 / 超时，视觉可区分
交互风格对齐 ThinkingBlock（Textual Collapsible）。
"""

import json

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Collapsible, Static

# 状态 → 图标 / 中文文案 / 样式类
_STATUS_META = {
    "running": ("⏳", "执行中", "tool-running"),
    "success": ("✅", "成功", "tool-success"),
    "error": ("❌", "失败", "tool-error"),
    "rejected": ("🚫", "被拒绝", "tool-rejected"),
    "timeout": ("⏱", "超时", "tool-timeout"),
}


class ToolBlock(Vertical):
    """单次工具调用的折叠卡片"""

    DEFAULT_CLASSES = "tool-block"

    def __init__(
        self,
        call_id: str,
        name: str,
        arguments: dict,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._call_id = call_id
        self._name = name
        self._arguments = arguments or {}
        self._status = "running"
        self._duration_ms = 0
        self._collapsible: Collapsible | None = None
        self._content: Static | None = None

    @property
    def call_id(self) -> str:
        return self._call_id

    def compose(self) -> ComposeResult:
        with Collapsible(collapsed=True, title=self._build_title()) as collapsible:
            self._collapsible = collapsible
            self._content = Static(self._build_body())
            yield self._content

    def on_mount(self) -> None:
        # compose 后兜底取引用
        if self._collapsible is None:
            for child in self.walk_children(Collapsible):
                self._collapsible = child
                break
        if self._content is None:
            for child in self.walk_children(Static):
                self._content = child
                break

    def _build_title(self) -> str:
        icon, status_text, _ = _STATUS_META.get(self._status, _STATUS_META["running"])
        duration = ""
        if self._status != "running" and self._duration_ms:
            duration = f" · {self._duration_ms}ms"
        return f"{icon} {self._name} · {status_text}{duration}"

    def _build_body(self, result_text: str = "") -> str:
        args_text = json.dumps(self._arguments, ensure_ascii=False, indent=2)
        body = f"参数:\n{args_text}"
        if result_text:
            body += f"\n\n结果:\n{result_text}"
        return body

    def set_result(self, status: str, result_text: str, duration_ms: int = 0) -> None:
        """更新执行状态与结果（执行完成 / 被拒绝 / 超时后调用）"""
        self._status = status if status in _STATUS_META else "error"
        self._duration_ms = duration_ms
        # 状态样式类切换（视觉区分）
        for _, (_, _, cls) in _STATUS_META.items():
            self.remove_class(cls)
        self.add_class(_STATUS_META[self._status][2])
        if self._collapsible is not None:
            self._collapsible.title = self._build_title()
        if self._content is not None:
            self._content.update(self._build_body(result_text))
