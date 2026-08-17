"""会话选择界面

/history 命令弹出，展示历史会话列表。
支持 ↑↓ 键选择、Enter 确认、鼠标单击/双击进入、Esc 取消。
"""

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.message import Message
from textual.screen import Screen
from textual.widgets import Label, ListItem, ListView

from bencode.config.schema import ProviderConfig
from bencode.provider.base import Role
from bencode.session.models import Session


class SessionSelectScreen(Screen):
    """会话选择界面

    展示历史会话列表，用户选择后发送 Selected 消息（由 App 处理屏幕切换）。
    """

    CSS = """
    SessionSelectScreen {
        align: center middle;
        background: $surface 60%;
    }

    #session-container {
        width: 70;
        height: auto;
        max-height: 28;
        padding: 1 2;
        border: thick $accent;
        background: $surface;
    }

    #session-title {
        text-align: center;
        text-style: bold;
        color: $accent;
        margin-bottom: 1;
    }

    #session-hint {
        color: $text-muted;
        text-align: center;
        margin-bottom: 1;
    }

    ListView {
        height: auto;
        max-height: 20;
    }

    ListItem {
        padding: 0 1;
    }

    ListItem:hover {
        background: $accent 20%;
    }

    ListItem.-active {
        text-style: bold;
        background: $accent 30%;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "取消"),
    ]

    class Selected(Message):
        """用户选择了某个会话"""

        def __init__(self, session: Session, fallback_provider: ProviderConfig) -> None:
            super().__init__()
            self.session = session
            self.fallback_provider = fallback_provider

    def __init__(
        self,
        sessions: list[Session],
        current_session_id: str,
        fallback_provider: ProviderConfig,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._sessions = sessions
        self._current_session_id = current_session_id
        self._fallback_provider = fallback_provider

    @staticmethod
    def _summary(session: Session) -> str:
        """取首条用户消息作为摘要"""
        for m in session.messages:
            if m.role == Role.USER and m.text.strip():
                text = m.text.strip().replace("\n", " ")
                return text[:30] + ("…" if len(text) > 30 else "")
        return "（空对话）"

    def compose(self) -> ComposeResult:
        with Vertical(id="session-container"):
            yield Label("📅 历史会话", id="session-title")
            yield Label("↑↓ 选择 · Enter / 单击 / 双击 进入 · Esc 取消", id="session-hint")

            items = []
            for s in self._sessions:
                marker = " 👈 当前" if s.session_id == self._current_session_id else ""
                date = s.created_at[5:16].replace("T", " ") if len(s.created_at) >= 16 else s.created_at
                desc = f"{s.session_id}  {self._summary(s)}\n    {s.provider_name} · {date}{marker}"
                items.append(ListItem(Label(desc)))

            yield ListView(*items)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """用户选择某个会话（Enter / 单击 / 双击均触发）"""
        index = event.list_view.index
        if index is not None and 0 <= index < len(self._sessions):
            selected = self._sessions[index]
            self.post_message(
                self.Selected(selected, self._fallback_provider)
            )

    def action_cancel(self) -> None:
        """取消选择，返回对话界面"""
        self.app.pop_screen()
