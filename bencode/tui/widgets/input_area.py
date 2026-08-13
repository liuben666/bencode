"""用户输入区组件

支持多行文本输入，Enter 发送消息，Shift+Enter 换行。
底部工具栏包含 Thinking 开关按钮和发送/停止按钮。
发送按钮在空闲时显示 ▶（三角），流式输出时显示 ■（方块）。
"""

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.events import Key
from textual.message import Message
from textual.widgets import Button, TextArea


class ChatTextArea(TextArea):
    """自定义输入框：Enter 发送，Shift+Enter 换行

    拦截 Enter 键，阻止 TextArea 默认的换行行为，
    改为通知父组件提交消息。
    """

    class EnterPressed(Message):
        """Enter 键按下事件（通知父组件提交）"""

    def on_key(self, event: Key) -> None:
        """处理键盘事件

        Enter：发送消息（阻止 TextArea 默认换行）
        Shift+Enter：如果终端支持则插入换行，否则同 Enter
        其余按键：不拦截，由 TextArea._on_key 正常处理
        """
        if event.key == "enter":
            event.stop()
            event.prevent_default()
            self.post_message(self.EnterPressed())
            return
        if event.key == "shift+enter":
            event.stop()
            event.prevent_default()
            self.insert("\n")
            return


class InputArea(Vertical):
    """用户输入区

    布局：
    - 上方：ChatTextArea 输入框
    - 下方：工具栏（Thinking 开关按钮 + 发送/停止按钮）

    发送按钮在空闲时显示 ▶，流式输出时显示 ■（可点击停止）。
    """

    DEFAULT_CLASSES = "input-area"

    class Submitted(Message):
        """用户提交消息事件"""

        def __init__(self, text: str, thinking_enabled: bool) -> None:
            super().__init__()
            self.text = text
            self.thinking_enabled = thinking_enabled

    class StopRequested(Message):
        """用户请求停止流式输出"""

    def __init__(self, thinking_enabled: bool = False, **kwargs) -> None:
        super().__init__(**kwargs)
        self._thinking_enabled = thinking_enabled

    def compose(self) -> ComposeResult:
        yield ChatTextArea(id="user-input", classes="user-input")
        with Horizontal(id="input-toolbar"):
            yield Button(
                self._thinking_label(),
                id="thinking-btn",
            )
            yield Button("▶", id="send-btn", variant="primary")

    def on_mount(self) -> None:
        # 设置 Thinking 按钮初始样式
        thinking_btn = self.query_one("#thinking-btn", Button)
        if self._thinking_enabled:
            thinking_btn.add_class("thinking-on")
        else:
            thinking_btn.add_class("thinking-off")
        self.query_one(ChatTextArea).focus()

    def _thinking_label(self) -> str:
        """生成 Thinking 按钮标签"""
        return "🧠 Thinking: ON" if self._thinking_enabled else "Thinking: OFF"

    def _do_submit(self) -> None:
        """执行提交：读取输入框文本和 Thinking 状态，发送消息"""
        text_area = self.query_one(ChatTextArea)
        text = text_area.text.strip()
        if text:
            self.post_message(self.Submitted(text, self._thinking_enabled))
            text_area.clear()

    def on_chat_text_area_enter_pressed(self, event: ChatTextArea.EnterPressed) -> None:
        """ChatTextArea 的 Enter 按下事件"""
        self._do_submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """按钮点击处理"""
        if event.button.id == "send-btn":
            if self.has_class("streaming"):
                # 流式输出中 → 请求停止
                self.post_message(self.StopRequested())
            else:
                # 空闲 → 发送
                self._do_submit()
        elif event.button.id == "thinking-btn":
            # 切换 Thinking 开关
            self._thinking_enabled = not self._thinking_enabled
            event.button.label = self._thinking_label()
            if self._thinking_enabled:
                event.button.add_class("thinking-on")
                event.button.remove_class("thinking-off")
            else:
                event.button.add_class("thinking-off")
                event.button.remove_class("thinking-on")

    def set_streaming(self, streaming: bool) -> None:
        """设置流式输出状态，更新发送按钮外观"""
        send_btn = self.query_one("#send-btn", Button)
        if streaming:
            send_btn.label = "■"
            self.add_class("streaming")
        else:
            send_btn.label = "▶"
            self.remove_class("streaming")

    def get_thinking_enabled(self) -> bool:
        """获取当前 Thinking 开关状态"""
        return self._thinking_enabled

    def focus_input(self) -> None:
        """聚焦到输入框"""
        self.query_one(ChatTextArea).focus()
