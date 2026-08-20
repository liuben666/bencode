"""工具执行器

职责：
1. 按名查找工具（未注册 → 结构化错误）
2. 参数校验（缺失/类型不符 → 结构化错误）
3. 异步执行 + 统一超时兜底
4. 捕获一切异常，包装为结构化 ToolResult（全程不向调用方抛异常）
5. 输出超过阈值时截断并标注原始长度
"""

import asyncio
import time
from typing import Optional

from bencode.tools.base import BaseTool, ToolError, ToolResult
from bencode.tools.registry import ToolRegistry

# JSON Schema type → Python 类型映射
_TYPE_MAP = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "array": list,
    "object": dict,
}


class ToolExecutor:
    """工具执行器"""

    def __init__(
        self,
        registry: ToolRegistry,
        default_timeout: float = 60.0,
        max_output_chars: int = 10000,
    ) -> None:
        self._registry = registry
        self._default_timeout = default_timeout
        self._max_output_chars = max_output_chars

    async def execute(self, name: str, arguments: Optional[dict]) -> ToolResult:
        """执行一个工具调用，任何失败都体现在返回值中，不抛异常"""
        start = time.monotonic()

        # 1. 按名查找
        try:
            tool = self._registry.get(name)
        except ToolError as e:
            return ToolResult(
                success=False,
                error=str(e),
                error_kind="tool",
                duration_ms=self._elapsed_ms(start),
            )

        # 2. 参数校验
        arguments = arguments or {}
        invalid = self._validate_arguments(tool, arguments)
        if invalid:
            return ToolResult(
                success=False,
                error=invalid,
                error_kind="tool",
                duration_ms=self._elapsed_ms(start),
            )

        # 3. 带超时执行 + 异常兜底
        timeout = tool.timeout_seconds or self._default_timeout
        try:
            output = await asyncio.wait_for(tool.execute(**arguments), timeout=timeout)
        except asyncio.TimeoutError:
            return ToolResult(
                success=False,
                error=f"工具执行超时（{int(timeout)} 秒），已终止",
                error_kind="timeout",
                duration_ms=self._elapsed_ms(start),
            )
        except ToolError as e:
            error_text = str(e)
            kind = "timeout" if "超时" in error_text else "tool"
            return ToolResult(
                success=False,
                error=error_text,
                error_kind=kind,
                duration_ms=self._elapsed_ms(start),
            )
        except Exception as e:  # noqa: BLE001 兜底捕获一切异常
            return ToolResult(
                success=False,
                error=f"工具内部异常 {type(e).__name__}: {e}",
                error_kind="internal",
                duration_ms=self._elapsed_ms(start),
            )

        # 4. 输出截断保护
        output = "" if output is None else str(output)
        original_length = len(output)
        truncated = original_length > self._max_output_chars
        if truncated:
            output = output[: self._max_output_chars] + (
                f"\n[输出超长，已截断：原始长度 {original_length} 字符]"
            )

        return ToolResult(
            success=True,
            output=output,
            truncated=truncated,
            original_length=original_length,
            duration_ms=self._elapsed_ms(start),
        )

    def _validate_arguments(self, tool: BaseTool, arguments: dict) -> Optional[str]:
        """按工具的参数 Schema 校验，返回错误文案或 None"""
        schema = tool.parameters or {}
        properties = schema.get("properties", {})
        required = schema.get("required", [])

        # 必填缺失（None 或空串视为缺失）
        missing = [key for key in required if arguments.get(key) in (None, "")]
        if missing:
            return f"缺少必填参数: {', '.join(missing)}"

        # 类型核对
        for key, value in arguments.items():
            spec = properties.get(key)
            if spec is None:
                continue  # 容忍未声明的多余参数
            expected = spec.get("type")
            python_type = _TYPE_MAP.get(expected)
            if python_type is None:
                continue
            # bool 是 int 子类，需先排除
            if isinstance(value, bool) and expected in ("integer", "number"):
                return f"参数类型错误: {key} 应为 {expected}，实际为 boolean"
            if not isinstance(value, python_type):
                return (
                    f"参数类型错误: {key} 应为 {expected}，"
                    f"实际为 {type(value).__name__}"
                )
        return None

    @staticmethod
    def _elapsed_ms(start: float) -> int:
        return int((time.monotonic() - start) * 1000)
