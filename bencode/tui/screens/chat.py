"""主对话界面

核心交互界面，包含消息列表和用户输入区。
处理用户输入、流式 AI 响应、会话管理等。
"""

import asyncio
from typing import Optional

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.screen import Screen
from textual.widgets import Header, Footer, Static
from textual import work

from bencode.config.schema import ProviderConfig
from bencode.provider.base import BaseProvider, MessageContent, Role, StreamChunk, ProviderError
from bencode.provider.factory import create_provider
from bencode.session.manager import SessionManager
from bencode.session.models import Session
from bencode.tui.widgets.input_area import InputArea
from bencode.tui.widgets.message_list import MessageList
from bencode.tui.screens.session_select import SessionSelectScreen


class ChatScreen(Screen):
    """主对话界面

    布局：
    - 顶部：Header
    - 中间：消息列表（MessageList）
    - 底部：用户输入区（InputArea）+ 状态栏
    """

    CSS = """
    ChatScreen {
        layout: vertical;
    }

    #chat-container {
        height: 1fr;
    }

    #status-bar {
        dock: bottom;
        height: 1;
        background: $primary;
        color: $text;
        padding: 0 2;
        content-align: center middle;
    }
    """

    class Exit(Message):
        """用户请求退出"""

    def __init__(
        self,
        provider_config: ProviderConfig,
        session: Optional[Session] = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._provider_config = provider_config
        self._session = session
        self._provider: Optional[BaseProvider] = None
        self._session_manager = SessionManager()
        self._is_streaming = False
        # 保存原始 thinking 配置，供开关恢复使用
        self._original_thinking = provider_config.thinking
        # 运行时 thinking 状态（可被开关动态切换）
        self._thinking_enabled = provider_config.thinking is not None
        # 流式 worker 引用（用于取消）
        self._stream_worker = None

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="chat-container"):
            yield MessageList()
            yield InputArea(thinking_enabled=self._thinking_enabled)
        yield Static(self._build_status_text(), id="status-bar")
        yield Footer()

    async def on_mount(self) -> None:
        """初始化 Provider 和会话"""
        # 创建 Provider 实例
        self._provider = create_provider(self._provider_config)

        # 创建或加载会话
        if self._session is None:
            self._session = self._session_manager.create_session(
                provider_name=self._provider_config.name,
                model=self._provider_config.model,
            )
            self._session_manager.save_session(self._session)

        # 更新状态栏
        self._update_status()

        # 加载历史消息（恢复会话时）
        if self._session.messages:
            message_list = self.query_one(MessageList)
            for msg in self._session.messages:
                if msg.role == Role.USER:
                    message_list.add_user_message(msg.text)
                elif msg.role == Role.ASSISTANT:
                    # start_ai_message 是 async，必须 await（否则 widget 未真正挂载，
                    # 后续 append_ai_text 更新的是未挂载的 widget，内容不可见/不可选）
                    await message_list.start_ai_message()
                    if msg.thinking_text:
                        message_list.add_thinking_block(msg.thinking_text)
                    message_list.append_ai_text(msg.text)
                    # finish_ai_message 是 async，必须 await
                    await message_list.finish_ai_message()

        # 聚焦输入框
        self.query_one(InputArea).focus_input()

    def _build_status_text(self) -> str:
        """构建状态栏文本"""
        provider = self._provider_config.name
        model = self._provider_config.model
        session_id = self._session.session_id if self._session else "N/A"
        thinking = "ON" if self._thinking_enabled else "OFF"
        return f"Provider: {provider}  |  Model: {model}  |  Thinking: {thinking}  |  Session: {session_id}"

    def _update_status(self) -> None:
        """更新状态栏"""
        status = self.query_one("#status-bar", Static)
        status.update(self._build_status_text())

    async def on_input_area_submitted(self, event: InputArea.Submitted) -> None:
        """处理用户提交消息"""
        if self._is_streaming:
            return

        text = event.text

        # 处理内置命令
        if text.startswith("/"):
            await self._handle_command(text)
            return

        # 根据 Thinking 开关状态更新 provider 配置
        self._thinking_enabled = event.thinking_enabled
        if event.thinking_enabled:
            # 开启 thinking：恢复原始配置或使用默认值
            if self._original_thinking:
                self._provider_config.thinking = self._original_thinking
            else:
                self._provider_config.thinking = {
                    "type": "enabled",
                    "budget_tokens": 10000,
                }
        else:
            # 关闭 thinking
            self._provider_config.thinking = None
        self._update_status()

        # 添加用户消息
        message_list = self.query_one(MessageList)
        message_list.add_user_message(text)

        # 保存用户消息到会话
        user_msg = MessageContent(role=Role.USER, text=text)
        self._session_manager.add_message_and_save(self._session, user_msg)

        # 标记正在流式输出（在启动 worker 前设置，防止重复提交）
        self._is_streaming = True
        # 更新发送按钮为停止状态
        self.query_one(InputArea).set_streaming(True)
        # 开始 AI 回复（作为 worker 运行，不阻塞消息泵，使流式渲染生效）
        self._stream_worker = self._stream_ai_response()

    async def _handle_command(self, command: str) -> None:
        """处理内置命令"""
        cmd = command.strip().lower()
        message_list = self.query_one(MessageList)
        if cmd == "/history":
            # 弹出会话选择界面（↑↓ 选择，Enter/鼠标点击进入）
            sessions = self._session_manager.list_recent_sessions(limit=15)
            # 过滤掉没有任何消息的空会话
            sessions = [s for s in sessions if s.messages]
            if not sessions:
                message_list.add_error_message("没有历史会话")
                return

            self.app.push_screen(
                SessionSelectScreen(
                    sessions=sessions,
                    current_session_id=self._session.session_id,
                    fallback_provider=self._provider_config,
                )
            )

        elif cmd in ("/quit", "/exit", "/q"):
            self.post_message(self.Exit())

        elif cmd == "/copy":
            # 复制最近一条 AI 回复到剪贴板
            last_ai = None
            for m in reversed(self._session.messages):
                if m.role == Role.ASSISTANT and m.text.strip():
                    last_ai = m.text
                    break
            if last_ai is None:
                message_list.add_error_message("没有可复制的 AI 回复")
                return
            self._copy_text_to_clipboard(last_ai)
            message_list.add_error_message(
                f"✅ 已复制最近一条 AI 回复（{len(last_ai)} 字符）到剪贴板"
            )

        elif cmd == "/help":
            help_text = (
                "## BenCode 命令\n\n"
                "- `/history` - 选择历史会话继续聊天（↑↓/Enter/鼠标）\n"
                "- `/copy` - 复制最近一条 AI 回复到剪贴板\n"
                "- `/quit` - 退出 BenCode\n"
                "- `/help` - 显示帮助\n\n"
                "## 复制文字技巧\n\n"
                "TUI 程序会捕获鼠标事件，终端原生拖选会被拦截。\n"
                "按住 **Shift** 再拖动鼠标即可原生选择复制。"
            )
            await message_list.start_ai_message()
            message_list.append_ai_text(help_text)
            await message_list.finish_ai_message()

        else:
            message_list.add_error_message(f"未知命令: {command}，输入 /help 查看可用命令")

    def _copy_text_to_clipboard(self, text: str) -> None:
        """复制文本到系统剪贴板（双保险）

        1. OSC 52 转义序列（Textual 内置，Windows Terminal 等现代终端支持）
        2. Windows clip 命令（更可靠的本地剪贴板写入，支持中文）
        """
        # 方式 1：OSC 52
        self.app.copy_to_clipboard(text)
        # 方式 2：Windows clip（UTF-16 LE + BOM 保证中文正确）
        try:
            import subprocess

            data = b"\xff\xfe" + text.encode("utf-16-le")
            subprocess.run(
                ["clip"],
                input=data,
                creationflags=0x08000000,  # CREATE_NO_WINDOW，避免闪黑窗
            )
        except Exception:
            pass

    @work
    async def _stream_ai_response(self) -> None:
        """流式获取 AI 回复

        作为 worker 运行，不阻塞消息泵，使 Textual 能在 chunk 之间处理重绘消息。
        """
        if self._provider is None:
            self._is_streaming = False
            return

        message_list = self.query_one(MessageList)
        await message_list.start_ai_message()

        # 本轮流式回复的缓冲区
        thinking_accumulated = ""  # 完整 thinking 文本
        text_accumulated = ""  # 完整正文文本
        thinking_signature: Optional[str] = None  # 多轮传递的 signature

        try:
            # 使用异步迭代器获取流式响应
            async for chunk in self._provider.chat_stream(self._session.messages):
                if chunk.type == "thinking":
                    # 累积 thinking 内容
                    thinking_accumulated += chunk.text
                    # 立即显示折叠的 thinking 区块（让用户看到"思考中"）
                    # 注意：传增量 chunk.text，ThinkingBlock 内部自行累加，
                    # 传累积文本会导致内容指数级重复
                    message_list.add_thinking_block(chunk.text)
                    # 让出事件循环，保持 UI 响应
                    await asyncio.sleep(0)

                elif chunk.type == "text":
                    # 追加正文
                    text_accumulated += chunk.text
                    message_list.append_ai_text(chunk.text)
                    # 让出事件循环，让 Textual 处理重绘消息，实现逐字流式效果
                    await asyncio.sleep(0)

                elif chunk.type == "done":
                    # 从 done chunk 提取 signature（多轮对话必须回传）
                    if chunk.metadata and chunk.metadata.get("thinking_signature"):
                        thinking_signature = chunk.metadata["thinking_signature"]

                    # 保存 AI 回复到会话
                    ai_msg = MessageContent(
                        role=Role.ASSISTANT,
                        text=text_accumulated,
                        thinking_text=thinking_accumulated if thinking_accumulated else None,
                        thinking_signature=thinking_signature,
                    )
                    self._session_manager.add_message_and_save(self._session, ai_msg)

                    # 异步完成 UI 渲染（必须 await）
                    await message_list.finish_ai_message()

        except ProviderError as e:
            message_list.add_error_message(str(e))
            await message_list.finish_ai_message()

        except asyncio.CancelledError:
            # 用户主动取消流式输出
            await message_list.finish_ai_message()
            raise

        except Exception as e:
            message_list.add_error_message(f"未知错误: {e}")
            await message_list.finish_ai_message()

        finally:
            self._is_streaming = False
            self._stream_worker = None
            # 恢复发送按钮为发送状态
            self.query_one(InputArea).set_streaming(False)
            # 重新聚焦输入框
            self.query_one(InputArea).focus_input()

    def on_input_area_stop_requested(self, event: InputArea.StopRequested) -> None:
        """用户点击停止按钮，取消流式输出"""
        if self._stream_worker is not None:
            self._stream_worker.cancel()

    def on_chat_screen_exit(self) -> None:
        """处理退出消息"""
        self.app.exit()
