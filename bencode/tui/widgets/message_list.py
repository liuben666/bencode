"""消息列表展示组件

负责渲染对话消息列表，支持：
- 用户消息和 AI 消息的差异化展示
- AI 回复使用 Markdown 组件渲染富文本
- Thinking 内容使用 ThinkingBlock 组件折叠展示
- 流式追加更新（流式期间用 Static + Rich Markdown 轻量渲染，
  流结束后替换为 Textual Markdown 做完整渲染）
"""

from rich.markdown import Markdown as RichMarkdown
from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.widgets import Markdown, Static

from bencode.tui.widgets.thinking_block import ThinkingBlock


class MessageList(VerticalScroll):
    """对话消息列表展示区

    所有对话消息都在此容器中展示。
    用户消息用带背景的 Static 展示，AI 回复用 Markdown 组件渲染。

    流式策略：
    - 流式期间使用 Static + rich.markdown.Markdown 轻量渲染（sync update，不阻塞）
    - 流结束后替换为 Textual Markdown 组件做完整富文本渲染
    """

    DEFAULT_CLASSES = "message-list"

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._current_ai_static: Static | None = None  # 流式期间的 Static 组件
        self._current_ai_container: Vertical | None = None
        self._ai_text_buffer: str = ""  # 流式追加时的文本缓冲区

    def add_user_message(self, text: str) -> None:
        """添加一条用户消息到列表"""
        container = Vertical(classes="user-message")
        self.mount(container)
        container.mount(Static("👤 你", classes="label"))
        container.mount(Static(text))
        self.scroll_end(animate=False)

    def start_ai_message(self) -> None:
        """开始一条新的 AI 回复

        创建 AI 消息容器和 Static 组件（流式期间用轻量渲染）。
        """
        self._ai_text_buffer = ""
        container = Vertical(classes="ai-message")
        self.mount(container)
        container.mount(Static("🤖 BenCode", classes="label"))
        static = Static("", classes="ai-content")
        container.mount(static)

        self._current_ai_static = static
        self._current_ai_container = container
        self.scroll_end(animate=False)

    def add_thinking_block(self, thinking_text: str) -> None:
        """在当前 AI 回复中添加 Thinking 折叠区块"""
        if self._current_ai_container is None or self._current_ai_static is None:
            return
        thinking = ThinkingBlock(thinking_text)
        # 插入到内容组件之前
        self._current_ai_container.mount(thinking, before=self._current_ai_static)
        self.scroll_end(animate=False)

    def append_ai_text(self, text: str) -> None:
        """追加流式文本到当前 AI 回复

        流式期间使用 Static + rich.markdown.Markdown 轻量渲染。
        Static.update() 是同步操作，仅设置 renderable 并 refresh，不阻塞事件循环。
        """
        if self._current_ai_static is None:
            return
        self._ai_text_buffer += text
        self._current_ai_static.update(RichMarkdown(self._ai_text_buffer))
        self.scroll_end(animate=False)

    def finish_ai_message(self) -> None:
        """结束当前 AI 回复

        将流式期间的 Static 替换为 Textual Markdown 组件，做完整富文本渲染。
        """
        if (
            self._current_ai_static is not None
            and self._current_ai_container is not None
        ):
            # 移除流式期间的 Static
            old_static = self._current_ai_static
            # 创建 Textual Markdown 做最终渲染
            markdown = Markdown(self._ai_text_buffer or "", classes="ai-content")
            # 用 Markdown 替换 Static
            self._current_ai_container.mount(markdown, before=old_static)
            old_static.remove()

        self._ai_text_buffer = ""
        self._current_ai_static = None
        self._current_ai_container = None

    def add_error_message(self, text: str) -> None:
        """添加一条错误消息"""
        error = Static(f"❌ {text}", classes="error-message")
        self.mount(error)
        self.scroll_end(animate=False)

    def clear_ai_buffer(self) -> None:
        """清空 AI 文本缓冲区（用于新一轮回复开始前）"""
        self._ai_text_buffer = ""
