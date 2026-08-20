"""主对话界面

核心交互界面，包含消息列表和用户输入区。
处理用户输入、流式 AI 响应、会话管理等。
"""

import asyncio
import os
from pathlib import Path
from typing import Optional

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.message import Message
from textual.screen import Screen
from textual.widgets import Header, Footer, Static
from textual import work

from bencode.config.schema import ProviderConfig
from bencode.provider.base import (
    BaseProvider,
    MessageContent,
    Role,
    StreamChunk,
    ToolCall,
    ProviderError,
)
from bencode.provider.factory import create_provider
from bencode.session.manager import SessionManager
from bencode.session.models import Session
from bencode.tools.base import ToolResult
from bencode.tools.executor import ToolExecutor
from bencode.tools.registry import ToolRegistry, create_default_registry
from bencode.tui.widgets.input_area import InputArea
from bencode.tui.widgets.message_list import MessageList
from bencode.tui.widgets.confirm_bar import ConfirmBar
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
        # 工具系统：注册中心 + 执行器
        self._tool_registry: ToolRegistry = create_default_registry()
        self._tool_executor = ToolExecutor(self._tool_registry)
        # 危险操作确认等待（ConfirmBar 显示期间非空，y/n 按键回填结果）
        self._pending_confirm: Optional[asyncio.Future] = None

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="chat-container"):
            yield MessageList()
            yield ConfirmBar()
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
                    # 历史工具调用以折叠卡片还原
                    for tc in msg.tool_calls or []:
                        message_list.add_tool_block(tc.id, tc.name, tc.arguments)
                    message_list.append_ai_text(msg.text)
                    # finish_ai_message 是 async，必须 await
                    await message_list.finish_ai_message()
                elif msg.role == Role.TOOL:
                    # 工具结果消息：更新对应卡片（不再单独渲染为文本）
                    self._restore_tool_result(message_list, msg)

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
        if cmd == "/new":
            # 开启新对话：创建新会话并清空当前消息列表
            # （当前会话已有内容时，已持久化到历史，可用 /history 找回）
            had_messages = bool(self._session.messages)
            self._session = self._session_manager.create_session(
                provider_name=self._provider_config.name,
                model=self._provider_config.model,
            )
            self._session_manager.save_session(self._session)
            message_list.clear()
            self._update_status()
            message_list.add_error_message(
                "已开启新对话" + ("（原对话已保存，可用 /history 找回）" if had_messages else "")
            )

        elif cmd.startswith("/tool"):
            # 手动直接执行工具（调试用，不经过模型）
            # 用法：/tool <name> [json参数]，如 /tool read_file {"path":"pyproject.toml"}
            # 必须以后台任务运行：确认流程依赖 ConfirmBar 消息回填，
            # 在事件处理器内直接 await 会阻塞消息泵导致死锁
            if self._is_streaming:
                message_list.add_error_message("正在执行中，请稍候")
                return
            self._is_streaming = True
            self.query_one(InputArea).set_streaming(True)
            asyncio.get_event_loop().create_task(
                self._run_manual_tool(command)
            )

        elif cmd == "/history":
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
                "- `/new` - 开启新对话（当前对话保存到历史，可用 /history 找回）\n"
                "- `/history` - 选择历史会话继续聊天（↑↓/Enter/鼠标）\n"
                "- `/tool <name> [json]` - 手动直接执行工具（调试用，不经过模型）\n"
                "  示例：`/tool read_file {\"path\":\"pyproject.toml\"}`\n"
                "- `/copy` - 复制最近一条 AI 回复到剪贴板\n"
                "- `/quit` - 退出 BenCode\n"
                "- `/help` - 显示帮助\n\n"
                "## 工具系统\n\n"
                "AI 可以调用工具读写文件、执行命令、搜索代码：\n"
                "- 读文件 / 查找 / 搜索：直接执行，结果以折叠卡片展示\n"
                "- 写文件 / 改文件 / 执行命令：执行前需按 y 确认（n 拒绝）\n"
                "- 点击卡片摘要行或回车可展开查看参数与结果\n"
                "- 本期单轮调用：工具执行一次后 AI 直接作答\n\n"
                "## 复制文字技巧\n\n"
                "TUI 程序会捕获鼠标事件，终端原生拖选会被拦截。\n"
                "按住 **Shift** 再拖动鼠标即可原生选择复制。"
            )
            await message_list.start_ai_message()
            message_list.append_ai_text(help_text)
            await message_list.finish_ai_message()

        else:
            message_list.add_error_message(f"未知命令: {command}，输入 /help 查看可用命令")

    async def _run_manual_tool(self, command: str) -> None:
        """手动工具执行入口（后台任务）：执行并复位流式状态

        异常兜底：任何错误都不允许让任务静默死亡，必须复位 UI 状态。
        """
        try:
            await self._handle_manual_tool(command)
        except Exception as e:
            self.query_one(MessageList).add_error_message(f"工具执行异常: {e}")
        finally:
            self._is_streaming = False
            self.query_one(InputArea).set_streaming(False)

    async def _handle_manual_tool(self, command: str) -> None:
        """手动直接执行工具（调试用，不经过模型、不写入会话）

        用法：
        - /tool                列出全部可用工具
        - /tool <name>         执行无参数工具
        - /tool <name> <json>  执行带参数工具，如 /tool read_file {"path":"pyproject.toml"}
        """
        import json as _json
        import time as _time

        message_list = self.query_one(MessageList)
        # 注意：不能用 lower() 后的 cmd（JSON 参数可能含大小写敏感内容如路径）
        # 按最多 3 段切分：["/tool", 工具名, json参数]
        parts = command.strip().split(maxsplit=2)

        # 无参数：以 Markdown 帮助信息列出全部工具及参数（非错误）
        if len(parts) < 2:
            lines = ["## 可用工具\n"]
            for tool_name in self._tool_registry.names():
                tool = self._tool_registry.get(tool_name)
                props = tool.parameters.get("properties", {}) if tool.parameters else {}
                required = set(tool.parameters.get("required", [])) if tool.parameters else set()
                if props:
                    param_desc = ", ".join(
                        f"`{p}`" + ("*" if p in required else "") for p in props
                    )
                else:
                    param_desc = "无参数"
                lines.append(f"- **{tool_name}**（{param_desc}）")
            lines.append(
                "\n带 `*` 的为必填参数。用法：`/tool <name> <json参数>`，"
                "如 `/tool read_file {\"path\":\"pyproject.toml\"}`"
            )
            await message_list.start_ai_message()
            message_list.append_ai_text("\n".join(lines))
            await message_list.finish_ai_message()
            return

        name = parts[1].strip()
        arguments: dict = {}
        if len(parts) >= 3:
            # 尝试解析 JSON 参数（解析失败给出明确提示）
            try:
                arguments = _json.loads(parts[2])
                if not isinstance(arguments, dict):
                    message_list.add_error_message("参数必须是 JSON 对象，如 {\"path\":\"a.txt\"}")
                    return
            except _json.JSONDecodeError as e:
                message_list.add_error_message(f"参数 JSON 解析失败: {e}")
                return

        # 未注册的工具直接提示
        if name not in self._tool_registry.names():
            message_list.add_error_message(
                f"未知工具: {name}，可用工具: {', '.join(self._tool_registry.names())}"
            )
            return

        # 直接执行（复用模型调用的渲染/确认/执行链路，但不写入会话）
        call = {
            "id": f"manual-{int(_time.time() * 1000)}",
            "name": name,
            "arguments": arguments,
        }
        await message_list.start_ai_message()
        try:
            await self._execute_single_tool(call, save_to_session=False)
        finally:
            await message_list.finish_ai_message()

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

    @staticmethod
    def _restore_tool_result(message_list: MessageList, msg: MessageContent) -> None:
        """恢复会话时，从工具结果文本推断状态并更新对应卡片"""
        text = msg.text or ""
        if "用户拒绝" in text:
            status = "rejected"
        elif text.startswith("[工具执行失败]"):
            status = "timeout" if "超时" in text else "error"
        else:
            status = "success"
        message_list.update_tool_block(msg.tool_call_id or "", status, text)

    @work
    async def _stream_ai_response(self) -> None:
        """流式获取 AI 回复（含工具调用闭环）

        作为 worker 运行，不阻塞消息泵，使 Textual 能在 chunk 之间处理重绘消息。

        单轮工具调用流程：
        1. 第一轮请求携带工具清单，流式解析正文/thinking/工具调用
        2. 有工具调用时：渲染卡片 → 危险操作确认 → 执行 → 结果写入会话
        3. 第二轮请求不再下发工具（收尾轮），模型基于工具结果作答，本轮结束
        """
        if self._provider is None:
            self._is_streaming = False
            return

        try:
            # 第一轮：允许工具调用
            tool_calls = await self._run_model_round(allow_tools=True)

            if tool_calls:
                # 执行工具并把结果写入会话
                await self._handle_tool_calls(tool_calls)
                # 第二轮：收尾轮不再下发工具，模型只能纯文本作答
                await self._run_model_round(allow_tools=False)

        except ProviderError as e:
            message_list = self.query_one(MessageList)
            await message_list.start_ai_message()
            message_list.add_error_message(str(e))
            await message_list.finish_ai_message()

        except asyncio.CancelledError:
            # 用户主动取消流式输出
            raise

        except Exception as e:
            message_list = self.query_one(MessageList)
            await message_list.start_ai_message()
            message_list.add_error_message(f"未知错误: {e}")
            await message_list.finish_ai_message()

        finally:
            self._is_streaming = False
            self._stream_worker = None
            # 恢复发送按钮为发送状态
            self.query_one(InputArea).set_streaming(False)
            # 重新聚焦输入框
            self.query_one(InputArea).focus_input()

    async def _run_model_round(self, allow_tools: bool) -> list[dict]:
        """执行一轮模型请求

        流式渲染 thinking/正文，收集工具调用；
        完成后把 assistant 消息（含工具调用）写入会话并持久化。

        Args:
            allow_tools: True 时请求携带工具清单并收集工具调用；
                         False 为收尾轮，若模型仍请求工具则提示并忽略（单轮边界）

        Returns:
            本轮流式解析出的工具调用元数据列表
        """
        message_list = self.query_one(MessageList)
        await message_list.start_ai_message()

        # 本轮流式回复的缓冲区
        thinking_accumulated = ""  # 完整 thinking 文本
        text_accumulated = ""  # 完整正文文本
        thinking_signature: Optional[str] = None  # 多轮传递的 signature
        tool_calls: list[dict] = []  # 工具调用元数据

        # 运行时注入环境上下文（不持久化）：让模型知道真实操作系统/路径，
        # 避免生成 Unix 命令或使用 %USERPROFILE%/~/ 等无法展开的写法
        context_messages = [self._build_env_context()] + self._session.messages

        # 使用异步迭代器获取流式响应（收尾轮不下发工具）
        async for chunk in self._provider.chat_stream(
            context_messages,
            tools=self._tool_registry if allow_tools else None,
        ):
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

            elif chunk.type == "tool_call":
                if not allow_tools:
                    # 单轮边界：收尾轮不再执行任何工具调用
                    message_list.add_error_message(
                        "⚠ 模型再次请求工具调用，本期不支持连续调用"
                        "（Agent Loop 将在下期支持），已忽略"
                    )
                    continue
                tool_calls.append(chunk.metadata or {})

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
            # 收尾轮出现的工具调用不落库（未执行，避免历史出现无结果的调用）
            # 注意：metadata 含 parse_error 等额外键，必须显式取字段构造
            tool_calls=(
                [
                    ToolCall(id=tc["id"], name=tc["name"], arguments=tc.get("arguments") or {})
                    for tc in tool_calls
                    if tc.get("id") and tc.get("name")
                ]
                if allow_tools
                else None
            ),
        )
        self._session_manager.add_message_and_save(self._session, ai_msg)

        # 异步完成 UI 渲染（必须 await）
        await message_list.finish_ai_message()
        return tool_calls

    async def _handle_tool_calls(self, tool_calls: list[dict]) -> None:
        """逐个执行工具调用：渲染卡片 → 危险确认 → 执行 → 结果写会话

        工具卡片需要挂载在 AI 消息容器内（与历史恢复的渲染结构一致），
        因此先开一条 AI 消息，执行完所有工具后收尾。
        """
        message_list = self.query_one(MessageList)
        await message_list.start_ai_message()
        try:
            for call in tool_calls:
                await self._execute_single_tool(call)
        finally:
            await message_list.finish_ai_message()

    async def _execute_single_tool(self, call: dict, save_to_session: bool = True) -> None:
        """执行单个工具调用：卡片渲染 → 确认 → 执行 → 结果落库

        save_to_session=False 时仅渲染卡片不写入会话（供 /tool 手动调试用）。
        """
        message_list = self.query_one(MessageList)
        call_id = call.get("id") or ""
        name = call.get("name") or ""
        arguments = call.get("arguments") or {}

        # 渲染折叠卡片（执行中状态）
        message_list.add_tool_block(call_id, name, arguments)

        # 参数 JSON 拼接失败：直接构造错误结果回灌（不可执行）
        if call.get("parse_error"):
            result = ToolResult(
                success=False,
                error=(
                    f"工具参数 JSON 解析失败（模型输出的参数不是合法 JSON），"
                    f"请重新发起调用并提供完整参数"
                ),
                error_kind="tool",
            )
            message_list.update_tool_block(
                call_id, "error", result.to_model_text()
            )
            if save_to_session:
                self._save_tool_message(call_id, result)
            return

        # 危险操作确认（写文件/改文件/执行命令）
        requires_confirmation = False
        try:
            requires_confirmation = self._tool_registry.get(
                name
            ).requires_confirmation
        except Exception:
            requires_confirmation = False
        if requires_confirmation:
            approved = await self._ask_confirmation(name, arguments)
            if not approved:
                result = ToolResult(
                    success=False,
                    error="用户拒绝执行该工具，请改用其他方式或直接向用户说明",
                    error_kind="tool",
                )
                message_list.update_tool_block(
                    call_id, "rejected", result.to_model_text()
                )
                if save_to_session:
                    self._save_tool_message(call_id, result)
                return

        # 执行器执行（内部含超时/异常/截断兜底，不抛异常）
        result = await self._tool_executor.execute(name, arguments)
        status = "success" if result.success else result.error_kind or "error"
        if status not in ("timeout", "error", "internal"):
            status = "error" if not result.success else "success"
        message_list.update_tool_block(
            call_id, status, result.to_model_text(), result.duration_ms
        )
        if save_to_session:
            self._save_tool_message(call_id, result)

    def _build_env_context(self) -> MessageContent:
        """构造运行时环境上下文消息（注入给模型，不持久化）

        提供真实操作系统、当前工作目录、用户目录/桌面路径等信息，
        避免模型生成 Unix 命令或使用 %USERPROFILE%/~/ 等无法展开的路径写法。
        """
        home = Path.home()
        desktop = home / "Desktop"
        if not desktop.exists():
            desktop = home / "桌面"
        lines = [
            "当前运行环境信息（工具调用必须遵守）：",
            f"- 操作系统: {os.name} (Windows)" if os.name == "nt" else f"- 操作系统: {os.name}",
            f"- 当前工作目录: {Path.cwd()}",
            f"- 用户主目录: {home}",
            f"- 桌面路径: {desktop}",
            "- 路径书写：使用 Windows 绝对路径（如 C:\\Users\\Administrator\\Desktop\\xxx）；"
            "  ~ 和 %USERPROFILE% 只在 run_command 中展开，文件系统工具（read_file/glob_files 等）不展开",
            "- 查看文件夹/目录内容请优先使用 glob_files 工具（列目录）",
            "- 执行命令用 run_command，Windows cmd 语法（列目录用 dir 而非 ls）",
        ]
        return MessageContent(role=Role.SYSTEM, text="\n".join(lines))

    async def _ask_confirmation(self, tool_name: str, arguments: dict) -> bool:
        """显示内联确认条并等待用户操作（按钮点击或 y/n 按键）

        确认条挂在输入框上方（不遮罩对话页面），聚焦到「允许」按钮：
        - 鼠标点击「允许/拒绝」按钮
        - 键盘 y/Enter 允许，n/Esc/q 拒绝
        通过 Future 回传结果；若确认流程异常则保守返回拒绝，不阻塞工具流程。
        """
        confirm_bar = self.query_one(ConfirmBar)
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending_confirm = future
        try:
            confirm_bar.show_confirm(tool_name, arguments)
            # 等待 ConfirmBar.Confirmed 事件回填（见 on_confirm_bar_confirmed）
            return await future
        except Exception:
            # 确认流程异常时不阻塞主流程，保守拒绝
            return False
        finally:
            confirm_bar.hide_confirm()
            self._pending_confirm = None
            # 恢复输入框焦点
            self.query_one(InputArea).focus_input()

    def on_confirm_bar_confirmed(self, event: ConfirmBar.Confirmed) -> None:
        """ConfirmBar 确认结果事件（按钮点击或 y/n 按键触发）"""
        if self._pending_confirm is not None and not self._pending_confirm.done():
            self._pending_confirm.set_result(event.approved)

    def _save_tool_message(self, call_id: str, result: ToolResult) -> None:
        """把工具结果作为 tool 角色消息写入会话并持久化"""
        tool_msg = MessageContent(
            role=Role.TOOL,
            text=result.to_model_text(),
            tool_call_id=call_id,
        )
        self._session_manager.add_message_and_save(self._session, tool_msg)

    def on_input_area_stop_requested(self, event: InputArea.StopRequested) -> None:
        """用户点击停止按钮，取消流式输出"""
        if self._stream_worker is not None:
            self._stream_worker.cancel()

    def on_chat_screen_exit(self) -> None:
        """处理退出消息"""
        self.app.exit()
