"""Thinking 折叠区块组件

可折叠的 thinking 展示组件：
- 默认折叠状态，显示"💭 Thinking..."摘要行
- 用户按 Tab 键展开查看完整 thinking 内容
- 折叠/展开状态切换有视觉反馈
"""

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Collapsible, Static


class ThinkingBlock(Vertical):
    """AI 扩展思考内容的可折叠展示组件

    默认折叠，只显示标题"💭 Thinking..."。
    用户点击或按快捷键可展开查看完整思考内容。
    """

    DEFAULT_CLASSES = "thinking-block"

    def __init__(
        self,
        thinking_text: str,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._thinking_text = thinking_text

    def compose(self) -> ComposeResult:
        with Collapsible(collapsed=True, title="💭 Thinking..."):
            yield Static(self._thinking_text)
