"""Provider 选择界面

启动时展示配置中所有 provider 列表，用户选择后进入对话。
支持键盘上下键选择、回车确认。
"""

from textual.app import ComposeResult
from textual.containers import Center, Vertical
from textual.message import Message
from textual.screen import Screen
from textual.widgets import Header, Label, ListItem, ListView

from bencode.config.schema import AppConfig, ProviderConfig


class ProviderSelectScreen(Screen):
    """Provider 选择界面

    展示所有配置的 provider 列表，用户选择后发送 Selected 消息。
    """

    CSS = """
    ProviderSelectScreen {
        align: center middle;
    }

    #select-container {
        width: 60;
        height: auto;
        max-height: 25;
        padding: 1 2;
        border: thick $accent;
        background: $surface;
    }

    #select-title {
        text-align: center;
        text-style: bold;
        color: $accent;
        margin-bottom: 1;
    }

    ListView {
        height: auto;
        max-height: 15;
    }

    ListItem {
        padding: 1 2;
    }

    ListItem:hover {
        background: $accent 20%;
    }

    ListItem.-active {
        text-style: bold;
        background: $accent 30%;
    }
    """

    class Selected(Message):
        """用户选择了某个 Provider"""

        def __init__(self, provider_config: ProviderConfig) -> None:
            super().__init__()
            self.provider_config = provider_config

    def __init__(self, config: AppConfig, **kwargs) -> None:
        super().__init__(**kwargs)
        self._config = config

    def compose(self) -> ComposeResult:
        yield Header()

        with Vertical(id="select-container"):
            yield Label("🚀 选择 AI 后端", id="select-title")
            yield Label("使用 ↑↓ 键选择，Enter 确认")

            items = []
            for provider in self._config.providers:
                thinking_tag = " [+thinking]" if provider.thinking else ""
                # 显示格式：名称（协议）· 模型 · 地址域名
                # 从 base_url 提取域名用于区分不同后端
                from urllib.parse import urlparse
                domain = urlparse(provider.base_url).hostname or provider.base_url
                desc = f"{provider.name}（{provider.protocol}）· {provider.model} · {domain}{thinking_tag}"
                items.append(ListItem(Label(desc)))

            yield ListView(*items)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """用户选择某个 provider"""
        index = event.list_view.index
        if index is not None and 0 <= index < len(self._config.providers):
            selected = self._config.providers[index]
            self.post_message(self.Selected(selected))
