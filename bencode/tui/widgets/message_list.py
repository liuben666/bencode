"""消息列表展示组件

负责渲染对话消息列表，支持：
- 用户消息和 AI 消息的差异化展示
- AI 回复使用 Rich Markdown 渲染富文本（单个 Static 组件，轻量稳定）
- Thinking 内容使用 ThinkingBlock 组件折叠展示
- 流式追加更新

渲染策略（关键）：
- 每条消息的容器必须 height: auto，否则 Vertical 默认 1fr 会瓜分视口高度，
  多条长消息会被挤压裁剪
- 最终渲染用 Static + RichMarkdown（一个 widget 渲染全部内容），
  而非 Textual Markdown 组件（后者为每个 markdown 元素创建子 widget，
  长对话会产生数千 widget 导致布局崩溃）
"""

from rich.markdown import Markdown as RichMarkdown
from textual.containers import Vertical, VerticalScroll
from textual.widgets import Static

from bencode.tui.widgets.thinking_block import ThinkingBlock
from bencode.tui.widgets.tool_block import ToolBlock


class MessageList(VerticalScroll):
    """对话消息列表展示区（垂直滚动）"""

    DEFAULT_CLASSES = "message-list"

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._current_ai_static: Static | None = None  # 当前 AI 消息的内容组件
        self._current_ai_container: Vertical | None = None
        self._ai_text_buffer: str = ""  # 流式追加的文本缓冲区
        self._thinking_block: ThinkingBlock | None = None  # 当前 thinking 组件
        # 全部工具卡片（按调用 ID 索引；跨轮次保留，供历史恢复/结果更新定位）
        self._tool_blocks: dict[str, ToolBlock] = {}

    def add_user_message(self, text: str) -> None:
        """添加一条用户消息到列表"""
        container = Vertical(classes="user-message")
        self.mount(container)
        container.mount(Static("👤 你", classes="label"))
        container.mount(Static(text))
        self.scroll_end(animate=False)

    async def start_ai_message(self) -> None:
        """开始一条新的 AI 回复

        异步实现：必须 await mount，否则后续 update 调用时 widget 未真正挂载，
        渲染内容会"消失"或无法被鼠标选中。
        """
        import asyncio as _asyncio

        self._ai_text_buffer = ""
        self._thinking_block = None
        container = Vertical(classes="ai-message")
        await self.mount(container)
        await container.mount(Static("🤖 BenCode", classes="label"))
        static = Static("", classes="ai-content")
        await container.mount(static)

        self._current_ai_static = static
        self._current_ai_container = container
        # 让出事件循环，确保 layout 完成
        await _asyncio.sleep(0)
        self.scroll_end(animate=False)

    def add_thinking_block(self, thinking_text: str) -> None:
        """在当前 AI 回复中添加/更新 Thinking 折叠区块

        第一次调用时创建 ThinkingBlock 并 mount；
        后续调用通过 update_text() 增量更新同一个组件。
        """
        if self._current_ai_container is None or self._current_ai_static is None:
            return
        if self._thinking_block is None:
            self._thinking_block = ThinkingBlock(thinking_text)
            self._current_ai_container.mount(
                self._thinking_block, before=self._current_ai_static
            )
        else:
            self._thinking_block.update_text(thinking_text)
        self.scroll_end(animate=False)

    def add_tool_block(self, call_id: str, name: str, arguments: dict) -> ToolBlock | None:
        """在当前 AI 回复中添加一张工具调用折叠卡片（初始为执行中状态）"""
        if self._current_ai_container is None or self._current_ai_static is None:
            return None
        block = ToolBlock(call_id, name, arguments)
        self._current_ai_container.mount(block, before=self._current_ai_static)
        self._tool_blocks[call_id] = block
        self.scroll_end(animate=False)
        return block

    def update_tool_block(
        self, call_id: str, status: str, result_text: str, duration_ms: int = 0
    ) -> None:
        """按调用 ID 更新工具卡片的状态与结果（也用于历史会话恢复）"""
        block = self._tool_blocks.get(call_id)
        if block is not None:
            block.set_result(status, result_text, duration_ms)
            self.scroll_end(animate=False)

    def append_ai_text(self, text: str) -> None:
        """追加流式文本到当前 AI 回复

        流式期间用纯文本渲染（最稳定，增量快），
        流结束时在 finish_ai_message 里切换为 Rich Markdown。
        """
        if self._current_ai_static is None:
            return
        self._ai_text_buffer += text
        self._current_ai_static.update(self._ai_text_buffer)
        self.scroll_end(animate=False)

    async def finish_ai_message(self) -> None:
        """结束当前 AI 回复

        用 Rich Markdown 完成最终渲染。
        关键：直接更新同一个 Static 组件的 renderable，不 mount/remove widget，
        避免 widget 树 churn（多次对话后布局损坏的根源）。
        """
        if self._current_ai_static is not None:
            self._current_ai_static.update(RichMarkdown(self._ai_text_buffer or ""))
            self.scroll_end(animate=False)

        self._ai_text_buffer = ""
        self._current_ai_static = None
        self._current_ai_container = None
        self._thinking_block = None

    def add_error_message(self, text: str) -> None:
        """添加一条错误/提示消息到列表"""
        error = Static(f"❌ {text}", classes="error-message")
        self.mount(error)
        self.scroll_end(animate=False)

    def clear(self) -> None:
        """清空消息列表及内部状态（用于开启新对话）"""
        self.remove_children()
        self._current_ai_static = None
        self._current_ai_container = None
        self._ai_text_buffer = ""
        self._thinking_block = None
        self._tool_blocks = {}
