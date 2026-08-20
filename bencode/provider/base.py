"""Provider 抽象接口定义

所有 LLM 后端适配器必须继承 BaseProvider 并实现其抽象方法。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, AsyncIterator, Optional

from bencode.config.schema import ProviderConfig

if TYPE_CHECKING:
    # 仅类型标注使用，避免运行时循环依赖
    from bencode.tools.registry import ToolRegistry


class Role(str, Enum):
    """消息角色"""
    SYSTEM = "system"  # 系统/环境上下文（运行时注入，不持久化）
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"  # 工具结果消息（回传给模型）


@dataclass
class ToolCall:
    """一次工具调用（模型发起）"""
    id: str  # 调用 ID，工具结果通过它关联
    name: str  # 工具名
    arguments: Optional[dict] = None  # 参数对象（已反序列化）

    def __post_init__(self) -> None:
        if self.arguments is None:
            self.arguments = {}


@dataclass
class MessageContent:
    """单条消息内容"""
    role: Role
    text: str
    thinking_text: Optional[str] = None  # extended thinking 内容，仅 assistant 可能有
    thinking_signature: Optional[str] = None  # thinking block 的 signature（多轮对话必须）
    # assistant 消息携带的工具调用列表（本轮模型请求执行的工具）
    tool_calls: Optional[list[ToolCall]] = None
    # tool 角色消息关联的调用 ID
    tool_call_id: Optional[str] = None


@dataclass
class StreamChunk:
    """流式响应的单个 chunk"""

    # chunk 类型：text 正文 / thinking 思考内容 / tool_call 工具调用 / done 流结束
    type: str  # "text" | "thinking" | "tool_call" | "done"
    text: str = ""
    # 额外元数据：
    # - thinking signature
    # - tool_call: {"id": 调用ID, "name": 工具名, "arguments": 参数dict}
    metadata: Optional[dict] = None


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
        tools: Optional["ToolRegistry"] = None,
    ) -> AsyncIterator[StreamChunk]:
        """
        流式发送对话请求，逐 chunk 返回响应。

        Args:
            messages: 历史消息列表（包含多轮上下文，可含工具调用/结果消息）
            tools: 工具注册中心；非 None 时请求携带工具清单，
                   适配器需解析流式工具调用并产出 type="tool_call" 的 chunk

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
