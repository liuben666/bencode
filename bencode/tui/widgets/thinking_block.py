"""Thinking 折叠区块组件

可折叠的 thinking 展示组件：
- 默认折叠状态，显示"💭 Thinking..."摘要行
- 用户点击或按快捷键展开查看完整 thinking 内容
- 支持流式追加：调用 update_text() 增量更新内容
"""

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Collapsible, Static


class ThinkingBlock(Vertical):
    """AI 扩展思考内容的可折叠展示组件

    默认折叠，只显示标题"💭 Thinking..."。
    用户点击或按快捷键可展开查看完整思考内容。

    流式期间调用 update_text() 增量更新内容，无需重新挂载。
    """

    DEFAULT_CLASSES = "thinking-block"

    def __init__(
        self,
        thinking_text: str = "",
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._thinking_text = thinking_text
        self._content_static: Static | None = None

    def compose(self) -> ComposeResult:
        with Collapsible(collapsed=True, title="💭 Thinking..."):
            self._content_static = Static(self._thinking_text)
            yield self._content_static

    def on_mount(self) -> None:
        # compose 后取一次引用
        if self._content_static is None:
            for child in self.walk_children(Static):
                self._content_static = child
                break

    def update_text(self, text: str) -> None:
        """追加更新 thinking 内容

        流式期间每个 thinking chunk 调用一次，无需重新创建组件。
        """
        self._thinking_text += text
        if self._content_static is not None:
            self._content_static.update(self._thinking_text)
