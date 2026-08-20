"""工具抽象接口与结构化结果模型

所有工具实现 BaseTool 统一接口：
- 元信息：名称、描述、参数 JSON Schema
- 执行入口：异步 execute 方法，返回输出文本
- 可预期失败统一抛 ToolError，由执行器捕获包装为 ToolResult
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional


class ToolError(Exception):
    """工具执行失败的业务异常

    工具内部把可预期的失败（文件不存在、匹配多处、命令退出码非 0 等）
    包装为该异常抛出，由执行器统一捕获转为结构化结果，
    不会向调用方（主流程）扩散导致崩溃。
    """


@dataclass
class ToolResult:
    """工具执行的结构化结果

    无论成功失败，一律以该结构返回；
    模型根据 error 信息决定重试、调整参数或换用其他方案。
    """

    success: bool  # 是否成功
    output: str = ""  # 正常输出内容
    error: str = ""  # 失败原因（人类可读，回传模型）
    error_kind: str = ""  # 失败类别："tool" 业务失败 / "timeout" 超时 / "internal" 内部异常
    truncated: bool = False  # 输出是否被截断
    original_length: int = 0  # 截断前的原始长度
    duration_ms: int = 0  # 执行耗时（毫秒）

    def to_model_text(self) -> str:
        """转为回灌给模型的文本"""
        parts: list[str] = []
        if self.output:
            parts.append(self.output)
        if not self.success and self.error:
            parts.append(f"[工具执行失败] {self.error}")
        if self.truncated:
            parts.append(f"[输出超长，已截断：原始长度 {self.original_length} 字符]")
        if not parts:
            parts.append("[工具执行成功，无输出]")
        return "\n".join(parts)


class BaseTool(ABC):
    """统一工具抽象接口

    子类通过类属性声明元信息：
    - name: 工具名（注册中心的唯一键）
    - description: 给模型看的用途说明
    - parameters: 参数 JSON Schema
    - requires_confirmation: 危险操作标记（执行前需用户确认）
    - timeout_seconds: 执行超时（秒），执行器按此兜底
    """

    requires_confirmation: bool = False
    timeout_seconds: float = 60.0

    name: str = ""
    description: str = ""
    parameters: dict = {}

    @abstractmethod
    async def execute(self, **kwargs: Any) -> str:
        """执行工具

        Args:
            **kwargs: 与 parameters Schema 对应的参数

        Returns:
            输出文本（回传模型）

        Raises:
            ToolError: 可预期的业务失败
        """
        ...


@dataclass
class ToolCall:
    """一次工具调用（模型发起）"""

    id: str  # 调用 ID（回传结果时关联）
    name: str  # 工具名
    arguments: dict = None  # 参数对象（已反序列化）

    def __post_init__(self) -> None:
        if self.arguments is None:
            self.arguments = {}
