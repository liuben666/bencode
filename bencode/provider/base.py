"""Provider 抽象接口定义

所有 LLM 后端适配器必须继承 BaseProvider 并实现其抽象方法。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import AsyncIterator, Optional

from bencode.config.schema import ProviderConfig


class Role(str, Enum):
    """消息角色"""
    USER = "user"
    ASSISTANT = "assistant"


@dataclass
class MessageContent:
    """单条消息内容"""
    role: Role
    text: str
    thinking_text: Optional[str] = None  # extended thinking 内容，仅 assistant 可能有
    thinking_signature: Optional[str] = None  # thinking block 的 signature（多轮对话必须）


@dataclass
class StreamChunk:
    """流式响应的单个 chunk"""

    # chunk 类型：text 为正文，thinking 为思考内容，done 表示流结束
    type: str  # "text" | "thinking" | "done"
    text: str = ""
    metadata: Optional[dict] = None  # 额外元数据（如 thinking signature）


class BaseProvider(ABC):
    """LLM Provider 抽象基类

    所有后端适配器必须实现此接口。
    子类需在 __init__ 中接收 ProviderConfig 并初始化客户端。
    """

    def __init__(self, config: ProviderConfig) -> None:
        self.config = config

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """返回 provider 显示名称"""
        ...

    @property
    @abstractmethod
    def model_name(self) -> str:
        """返回当前使用的模型名称"""
        ...

    @abstractmethod
    async def chat_stream(
        self,
        messages: list[MessageContent],
    ) -> AsyncIterator[StreamChunk]:
        """
        流式发送对话请求，逐 chunk 返回响应。

        Args:
            messages: 历史消息列表（包含多轮上下文）

        Yields:
            StreamChunk: 流式响应的每个 chunk

        Raises:
            ProviderError: API 请求失败时抛出
        """
        ...
        # 让 async generator 语法合法
        if False:
            yield


class ProviderError(Exception):
    """Provider API 调用错误"""
