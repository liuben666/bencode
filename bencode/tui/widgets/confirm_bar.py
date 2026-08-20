"""危险工具操作内联确认条（Claude Code 风格，按钮操作）

写在输入框上方的一条紧凑确认 UI，不遮罩整个对话页面：
- 第一行：工具名 + 参数摘要
- 第二行：右侧「允许」「拒绝」两个按钮（鼠标点击即可确认）
- 键盘 y / Enter 允许，n / Esc / q 拒绝（焦点在确认条区域时生效）
- 无确认等待时组件隐藏，不占用布局空间
"""

import json

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widgets import Button, Static

# 参数摘要最大长度，避免确认条被超大参数撑爆
_MAX_SUMMARY_CHARS = 200


class ConfirmBar(Vertical):
    """危险操作确认条（按钮 + 键盘快捷键）"""

    DEFAULT_CLASSES = "confirm-bar"
    # 可聚焦：显示时焦点移到这里，y/n 快捷键才不会被输入框吞掉
    can_focus = True

    BINDINGS = [
        ("y", "allow", "允许"),
        ("enter", "allow", "允许"),
        ("n", "deny", "拒绝"),
        ("escape", "deny", "拒绝"),
        ("q", "deny", "拒绝"),
    ]

    class Confirmed(Message):
        """确认结果事件：approved=True 允许，False 拒绝"""

        def __init__(self, approved: bool) -> None:
            super().__init__()
            self.approved = approved

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._tool_name = ""
        self._arguments: dict = {}
        # 初始强制隐藏，避免 CSS display: none 在某些布局下失效
        self.visible = False

    def compose(self) -> ComposeResult:
        yield Static("", id="confirm-info")
        with Horizontal(id="confirm-actions"):
            yield Button("允许 (y)", id="confirm-allow-btn", variant="success")
            yield Button("拒绝 (n)", id="confirm-deny-btn", variant="error")

    def show_confirm(self, tool_name: str, arguments: dict) -> None:
        """显示确认条，聚焦到「允许」按钮并准备接收操作"""
        self._tool_name = tool_name
        self._arguments = arguments or {}
        # 用 Rich 标准标签（[bold red]/[dim]），Textual 不支持 class= 属性语法
        info = (
            f"[bold red]⚠ 危险操作确认  {tool_name}[/bold red]  "
            f"[dim]{self._summary()}[/dim]"
        )
        self.query_one("#confirm-info", Static).update(info)
        self.visible = True
        # 布局刷新后再聚焦（组件刚可见，立即 focus 可能失败）
        self.call_after_refresh(
            lambda: self.query_one("#confirm-allow-btn", Button).focus()
        )

    def hide_confirm(self) -> None:
        """隐藏确认条"""
        self.visible = False

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """按钮点击：允许/拒绝"""
        if event.button.id == "confirm-allow-btn":
            self.action_allow()
        elif event.button.id == "confirm-deny-btn":
            self.action_deny()

    def action_allow(self) -> None:
        """允许执行（按钮点击或 y/Enter 触发）"""
        self.post_message(self.Confirmed(True))

    def action_deny(self) -> None:
        """拒绝执行（按钮点击或 n/Esc/q 触发）"""
        self.post_message(self.Confirmed(False))

    def _summary(self) -> str:
        """参数摘要（紧凑单行，超长截断）"""
        text = json.dumps(self._arguments, ensure_ascii=False, separators=(",", ":"))
        if len(text) > _MAX_SUMMARY_CHARS:
            text = text[:_MAX_SUMMARY_CHARS] + "…（参数过长，已截断）"
        return text
