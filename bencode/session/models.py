"""会话数据模型定义"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from bencode.provider.base import MessageContent


@dataclass
class Session:
    """单个对话会话"""

    session_id: str  # 唯一会话 ID
    created_at: str  # 创建时间（ISO 格式）
    provider_name: str  # 使用的 provider 名称
    model: str  # 使用的模型名称
    messages: list[MessageContent] = field(default_factory=list)  # 消息列表

    def add_message(self, message: MessageContent) -> None:
        """添加一条消息到会话"""
        self.messages.append(message)

    def to_dict(self) -> dict:
        """序列化为可 JSON 化的字典"""
        return {
            "session_id": self.session_id,
            "created_at": self.created_at,
            "provider_name": self.provider_name,
            "model": self.model,
            "messages": [
                {
                    "role": msg.role.value,
                    "text": msg.text,
                    "thinking_text": msg.thinking_text,
                    "thinking_signature": msg.thinking_signature,
                }
                for msg in self.messages
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Session":
        """从字典反序列化为 Session 对象"""
        from bencode.provider.base import Role

        messages = []
        for msg_data in data.get("messages", []):
            messages.append(MessageContent(
                role=Role(msg_data["role"]),
                text=msg_data["text"],
                thinking_text=msg_data.get("thinking_text"),
                thinking_signature=msg_data.get("thinking_signature"),
            ))

        return cls(
            session_id=data["session_id"],
            created_at=data["created_at"],
            provider_name=data["provider_name"],
            model=data.get("model", ""),
            messages=messages,
        )
