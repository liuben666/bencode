"""会话管理器：持久化与加载

会话文件存储在 ~/.bencode/sessions/ 目录下，每个会话一个 JSON 文件。
文件名格式：<session_id>.json
"""

import json
import os
import uuid
from datetime import datetime
from typing import Optional

from bencode.provider.base import MessageContent
from bencode.session.models import Session

# 会话存储目录
SESSIONS_DIR = os.path.join(os.path.expanduser("~"), ".bencode", "sessions")


class SessionManager:
    """会话管理器

    负责：创建新会话、加载已有会话、保存会话、列出最近会话。
    """

    def __init__(self, sessions_dir: Optional[str] = None) -> None:
        self._sessions_dir = sessions_dir or SESSIONS_DIR
        # 确保目录存在
        os.makedirs(self._sessions_dir, exist_ok=True)

    def create_session(
        self,
        provider_name: str,
        model: str,
    ) -> Session:
        """创建新会话

        Args:
            provider_name: 使用的 provider 名称
            model: 使用的模型名称

        Returns:
            Session: 新创建的会话对象（尚未持久化，需调用 save_session）
        """
        session_id = uuid.uuid4().hex[:12]
        now = datetime.now().isoformat()
        return Session(
            session_id=session_id,
            created_at=now,
            provider_name=provider_name,
            model=model,
        )

    def save_session(self, session: Session) -> None:
        """持久化会话到文件

        Args:
            session: 要保存的会话对象
        """
        file_path = os.path.join(
            self._sessions_dir, f"{session.session_id}.json"
        )
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(session.to_dict(), f, ensure_ascii=False, indent=2)

    def load_session(self, session_id: str) -> Optional[Session]:
        """加载指定会话

        Args:
            session_id: 会话 ID

        Returns:
            Session 对象，若文件不存在则返回 None
        """
        file_path = os.path.join(self._sessions_dir, f"{session_id}.json")
        if not os.path.exists(file_path):
            return None
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return Session.from_dict(data)

    def list_recent_sessions(self, limit: int = 20) -> list[Session]:
        """列出最近的会话

        按修改时间倒序排列，返回最近 limit 个会话。

        Args:
            limit: 返回的最大数量

        Returns:
            Session 列表
        """
        sessions = []
        if not os.path.exists(self._sessions_dir):
            return sessions

        # 获取所有 .json 文件，按修改时间排序
        json_files = []
        for fname in os.listdir(self._sessions_dir):
            if fname.endswith(".json"):
                fpath = os.path.join(self._sessions_dir, fname)
                mtime = os.path.getmtime(fpath)
                json_files.append((fname, mtime))

        # 按修改时间倒序
        json_files.sort(key=lambda x: x[1], reverse=True)

        # 只取前 limit 个
        for fname, _ in json_files[:limit]:
            fpath = os.path.join(self._sessions_dir, fname)
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                sessions.append(Session.from_dict(data))
            except (json.JSONDecodeError, KeyError):
                # 跳过损坏的会话文件
                continue

        return sessions

    def add_message_and_save(
        self,
        session: Session,
        message: MessageContent,
    ) -> None:
        """添加消息到会话并立即持久化

        Args:
            session: 会话对象
            message: 要添加的消息
        """
        session.add_message(message)
        self.save_session(session)
