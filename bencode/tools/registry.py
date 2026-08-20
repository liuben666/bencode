"""工具注册中心

集中登记工具、按名查找、导出为各 API 协议认得的工具清单：
- OpenAI 协议：{"type": "function", "function": {name, description, parameters}}
- Anthropic 协议：{name, description, input_schema}
"""

from bencode.tools.base import BaseTool, ToolError
from bencode.tools.builtin import (
    EditFileTool,
    GlobFilesTool,
    GrepSearchTool,
    ReadFileTool,
    RunCommandTool,
    WriteFileTool,
)


class ToolRegistry:
    """工具注册中心"""

    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        """登记一个工具，名称重复视为注册错误"""
        if tool.name in self._tools:
            raise ValueError(f"工具重复注册: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> BaseTool:
        """按名查找工具，未注册时报错（错误信息含工具名）"""
        tool = self._tools.get(name)
        if tool is None:
            raise ToolError(f"未注册的工具: {name}")
        return tool

    def names(self) -> list[str]:
        """已注册的全部工具名"""
        return list(self._tools.keys())

    def __len__(self) -> int:
        return len(self._tools)

    def to_openai_tools(self) -> list[dict]:
        """导出 OpenAI Chat Completions 认得的工具清单"""
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                },
            }
            for tool in self._tools.values()
        ]

    def to_anthropic_tools(self) -> list[dict]:
        """导出 Anthropic Messages API 认得的工具清单"""
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.parameters,
            }
            for tool in self._tools.values()
        ]


def create_default_registry() -> ToolRegistry:
    """创建登记了六个内置工具的注册中心"""
    registry = ToolRegistry()
    for tool_cls in (
        ReadFileTool,
        WriteFileTool,
        EditFileTool,
        RunCommandTool,
        GlobFilesTool,
        GrepSearchTool,
    ):
        registry.register(tool_cls())
    return registry
