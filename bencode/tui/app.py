"""BenCode Textual 主应用

负责应用生命周期管理、屏幕切换、全局配置加载。
"""

from textual.app import App, ComposeResult
from textual.binding import Binding

from bencode.config.loader import load_config, ConfigError
from bencode.config.schema import AppConfig, ProviderConfig
from bencode.session.manager import SessionManager
from bencode.tui.screens.provider_select import ProviderSelectScreen
from bencode.tui.screens.session_select import SessionSelectScreen
from bencode.tui.screens.chat import ChatScreen


class BenCodeApp(App):
    """BenCode 主应用

    启动流程：
    1. 加载配置
    2. 根据 --provider 参数决定是否跳过选择界面
    3. 展示 Provider 选择界面 或 直接进入对话
    """

    TITLE = "BenCode"
    SUB_TITLE = "终端 AI 编程助手"
    CSS_PATH = "styles.tcss"

    BINDINGS = [
        Binding("ctrl+q", "quit", "退出", show=True),
    ]

    def __init__(
        self,
        config: AppConfig,
        provider_name: str | None = None,
        session_id: str | None = None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._config = config
        self._provider_name = provider_name
        self._session_id = session_id
        self._session_manager = SessionManager()

    def on_mount(self) -> None:
        """应用挂载后，决定进入哪个界面"""
        if self._provider_name:
            # 通过 --provider 指定了 provider，直接进入对话
            provider_config = self._config.get_provider(self._provider_name)
            if provider_config is None:
                self.exit(
                    message=f"错误：未找到名为 '{self._provider_name}' 的 provider 配置"
                )
                return

            # 加载指定会话（如有）
            session = None
            if self._session_id:
                session = self._session_manager.load_session(self._session_id)
                if session is None:
                    self.exit(
                        message=f"错误：未找到会话 '{self._session_id}'"
                    )
                    return

            self._enter_chat(provider_config, session)
        else:
            # 未指定 provider，展示选择界面
            self._show_provider_select()

    def _show_provider_select(self) -> None:
        """展示 Provider 选择界面"""
        select_screen = ProviderSelectScreen(self._config)
        self.push_screen(select_screen)

    def _enter_chat(
        self,
        provider_config: ProviderConfig,
        session=None,
    ) -> None:
        """进入对话界面"""
        # 如果指定了 session_id 但还没加载
        if session is None and self._session_id:
            session = self._session_manager.load_session(self._session_id)

        chat_screen = ChatScreen(
            provider_config=provider_config,
            session=session,
        )
        self.push_screen(chat_screen)

    def on_provider_select_screen_selected(
        self, event: ProviderSelectScreen.Selected
    ) -> None:
        """用户在 Provider 选择界面选中了某个 provider"""
        self.pop_screen()  # 关闭选择界面
        self._enter_chat(event.provider_config)

    def on_session_select_screen_selected(
        self, event: "SessionSelectScreen.Selected"
    ) -> None:
        """用户在会话选择界面选中了某个历史会话

        关闭选择界面，用选中会话替换当前对话界面。
        provider 优先用会话记录的名称解析，找不到则沿用当前 provider。
        """
        session = event.session
        provider_config = (
            self._config.get_provider(session.provider_name)
            or event.fallback_provider
        )
        chat_screen = ChatScreen(
            provider_config=provider_config,
            session=session,
        )
        self.pop_screen()  # 关闭会话选择界面
        self.switch_screen(chat_screen)  # 替换当前对话界面

    def on_chat_screen_exit(self, event: ChatScreen.Exit) -> None:
        """用户在对话界面请求退出"""
        self.exit()
