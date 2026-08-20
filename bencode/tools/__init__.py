"""BenCode 工具系统

统一工具接口 + 六个核心工具 + 注册中心 + 执行器。
"""

from bencode.tools.base import BaseTool, ToolCall, ToolError, ToolResult
from bencode.tools.builtin import (
    EditFileTool,
    GlobFilesTool,
    GrepSearchTool,
    ReadFileTool,
    RunCommandTool,
    WriteFileTool,
)
from bencode.tools.executor import ToolExecutor
from bencode.tools.registry import ToolRegistry, create_default_registry

__all__ = [
    "BaseTool",
    "ToolCall",
    "ToolError",
    "ToolResult",
    "ReadFileTool",
    "WriteFileTool",
    "EditFileTool",
    "RunCommandTool",
    "GlobFilesTool",
    "GrepSearchTool",
    "ToolExecutor",
    "ToolRegistry",
    "create_default_registry",
]
