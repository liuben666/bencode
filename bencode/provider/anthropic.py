"""Anthropic Claude 适配器

基于 Anthropic Python SDK 实现流式对话与 extended thinking。

关键 API 参考（来源：context7 MCP 查询 Anthropic Python SDK 官方文档）：
- 异步流式：AsyncAnthropic().messages.stream() 上下文管理器
- Extended thinking：请求参数 thinking={"type": "enabled", "budget_tokens": N}
- 流式事件类型：thinking / text（MessageStream 高层封装）
- 多轮 thinking 传递：需将 thinking block（含 signature）原样回传
- 工具调用：
  - tools 参数：[{"name", "description", "input_schema"}]
  - 流式解析：content_block_start（tool_use 块，含 id/name）+
    content_block_delta（input_json_delta.partial_json 碎片拼接）+
    content_block_stop（块结束，整体反序列化）
  - 结果回传：user 消息内 tool_result 块（含 tool_use_id），
    必须紧跟携带 tool_use 的 assistant 消息
"""

import json
from typing import AsyncIterator, Optional

import anthropic

from bencode.config.schema import ProviderConfig
from bencode.provider.base import BaseProvider, MessageContent, Role, StreamChunk, ProviderError


class AnthropicProvider(BaseProvider):
    """Anthropic Claude 后端适配器"""

    def __init__(self, config: ProviderConfig) -> None:
        super().__init__(config)
        # 使用异步客户端，支持流式
        self._client = anthropic.AsyncAnthropic(
            api_key=config.api_key,
            base_url=config.base_url,
        )

    @property
    def provider_name(self) -> str:
        return f"Anthropic ({self.config.name})"

    @property
    def model_name(self) -> str:
        return self.config.model

    def _build_messages(self, messages: list[MessageContent]) -> list[dict]:
        """将统一消息格式转换为 Anthropic API 所需格式

        Anthropic 的消息格式：
        - role: "user" | "assistant"
        - content: 字符串或内容块列表
        - thinking 块在 assistant 消息中需以 content block 形式传递
          （多轮对话时必须包含 signature 字段以保证推理链连续性）
        - assistant 工具调用 → tool_use 块（含 id/name/input）
        - tool 角色结果消息 → user 消息内的 tool_result 块（含 tool_use_id），
          连续多条工具结果合并进同一条 user 消息
        """
        result = []
        for msg in messages:
            if msg.role == Role.SYSTEM:
                # system 消息不进入 messages，由调用方提取为顶层 system 参数
                continue
            elif msg.role == Role.USER:
                result.append({"role": "user", "content": msg.text})
            elif msg.role == Role.ASSISTANT:
                content_blocks = []
                # 如果有 thinking 内容，需要作为 thinking block 传入
                # 多轮对话必须传 signature，否则 API 会拒绝请求
                if msg.thinking_text:
                    thinking_block: dict = {
                        "type": "thinking",
                        "thinking": msg.thinking_text,
                    }
                    if msg.thinking_signature:
                        thinking_block["signature"] = msg.thinking_signature
                    content_blocks.append(thinking_block)
                if msg.text:
                    content_blocks.append({"type": "text", "text": msg.text})
                # 工具调用 → tool_use 块
                for tc in msg.tool_calls or []:
                    content_blocks.append({
                        "type": "tool_use",
                        "id": tc.id,
                        "name": tc.name,
                        "input": tc.arguments or {},
                    })
                result.append({"role": "assistant", "content": content_blocks})
            elif msg.role == Role.TOOL:
                # 工具结果 → user 消息内 tool_result 块；
                # 连续的工具结果合并到同一条 user 消息（API 要求紧跟 tool_use）
                tool_result_block = {
                    "type": "tool_result",
                    "tool_use_id": msg.tool_call_id or "",
                    "content": [{"type": "text", "text": msg.text}],
                }
                if (
                    result
                    and result[-1].get("role") == "user"
                    and isinstance(result[-1].get("content"), list)
                    and result[-1]["content"]
                    and result[-1]["content"][0].get("type") == "tool_result"
                ):
                    result[-1]["content"].append(tool_result_block)
                else:
                    result.append({
                        "role": "user",
                        "content": [tool_result_block],
                    })
        return result

    async def chat_stream(
        self,
        messages: list[MessageContent],
        tools=None,
    ) -> AsyncIterator[StreamChunk]:
        """流式发送对话请求

        使用 AsyncAnthropic 的 messages.stream() 上下文管理器，
        遍历流式事件，将 thinking / text / tool_use 事件转换为统一的 StreamChunk。

        thinking block 的 signature 通过 content_block_stop 事件捕获，
        并在 done chunk 的 metadata 中返回（多轮对话必须回传）。

        工具调用解析（原生 tool_use 内容块）：
        - content_block_start：块类型为 tool_use 时记录 id/name
        - content_block_delta：input_json_delta.partial_json 逐片拼接
        - content_block_stop：整体反序列化，产出 tool_call chunk
        """
        try:
            # 提取 system 消息为 Anthropic 顶层 system 参数（不在 messages 中）
            system_text = "\n\n".join(
                m.text for m in messages if m.role == Role.SYSTEM and m.text
            )
            # 构建请求参数
            kwargs = {
                "model": self.config.model,
                "max_tokens": 4096,
                "messages": self._build_messages(messages),
            }
            if system_text:
                kwargs["system"] = system_text

            # 如果配置了 thinking，添加扩展思考参数
            if self.config.thinking and self.config.thinking.get("type") == "enabled":
                budget_tokens = self.config.thinking.get("budget_tokens", 10000)
                kwargs["thinking"] = {
                    "type": "enabled",
                    "budget_tokens": budget_tokens,
                }
                # 启用 thinking 时，max_tokens 需要大于 budget_tokens
                if kwargs["max_tokens"] <= budget_tokens:
                    kwargs["max_tokens"] = budget_tokens + 4096

            # 携带工具清单（收尾轮不传 tools，模型只能纯文本作答）
            if tools is not None:
                kwargs["tools"] = tools.to_anthropic_tools()

            thinking_accumulated = ""  # 累积完整 thinking 文本
            thinking_signature: Optional[str] = None  # 多轮传递用
            # tool_use 块聚合器：index → {"id", "name", "json"}
            tool_blocks: dict[int, dict] = {}

            async with self._client.messages.stream(**kwargs) as stream:
                async for event in stream:
                    if event.type == "thinking":
                        # 思考内容增量，立即 yield（让 UI 立刻显示思考中）
                        thinking_accumulated += event.thinking
                        yield StreamChunk(
                            type="thinking",
                            text=event.thinking,
                        )
                    elif event.type == "text":
                        # 正文内容增量
                        yield StreamChunk(
                            type="text",
                            text=event.text,
                        )
                    elif event.type == "content_block_start":
                        # tool_use 块开始：记录调用 ID 与工具名
                        block = getattr(event, "content_block", None)
                        if block is not None and getattr(block, "type", "") == "tool_use":
                            tool_blocks[event.index] = {
                                "id": getattr(block, "id", "") or "",
                                "name": getattr(block, "name", "") or "",
                                "json": "",
                            }
                    elif event.type == "content_block_delta":
                        # tool_use 参数碎片：input_json_delta 逐片拼接
                        delta = getattr(event, "delta", None)
                        if (
                            delta is not None
                            and getattr(delta, "type", "") == "input_json_delta"
                            and event.index in tool_blocks
                        ):
                            tool_blocks[event.index]["json"] += (
                                getattr(delta, "partial_json", "") or ""
                            )
                    elif event.type == "content_block_stop":
                        block = getattr(event, "content_block", None)
                        if block is not None and getattr(block, "type", "") == "thinking":
                            # 抓取 thinking block 的 signature（多轮对话必须）
                            if (
                                hasattr(block, "signature")
                                and block.signature
                            ):
                                thinking_signature = block.signature
                        # tool_use 块结束：整体反序列化，产出完整工具调用
                        if event.index in tool_blocks:
                            slot = tool_blocks.pop(event.index)
                            arguments, parse_error = self._parse_tool_arguments(
                                slot["json"]
                            )
                            yield StreamChunk(
                                type="tool_call",
                                metadata={
                                    "id": slot["id"],
                                    "name": slot["name"],
                                    "arguments": arguments,
                                    # 参数 JSON 拼接后非法时置 True，由上层转为错误结果回灌
                                    "parse_error": parse_error,
                                },
                            )

            # 流结束：通过 done chunk 的 metadata 传递 signature
            yield StreamChunk(
                type="done",
                metadata={"thinking_signature": thinking_signature} if thinking_signature else {},
            )

        except anthropic.APIConnectionError as e:
            raise ProviderError(f"Anthropic API 连接失败: {e}") from e
        except anthropic.RateLimitError as e:
            raise ProviderError(f"Anthropic API 请求频率超限: {e}") from e
        except anthropic.APIStatusError as e:
            raise ProviderError(
                f"Anthropic API 错误 (状态码 {e.status_code}): {e.message}"
            ) from e
        except Exception as e:
            raise ProviderError(f"Anthropic API 未知错误: {e}") from e

    @staticmethod
    def _parse_tool_arguments(arguments_text: str) -> tuple[dict, bool]:
        """反序列化拼接完成的工具参数 JSON 字符串

        Returns:
            (参数对象, 是否解析失败)；失败时返回空对象并标记，由上层回灌错误
        """
        text = (arguments_text or "").strip()
        if not text:
            return {}, False
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return {}, True
        if not isinstance(parsed, dict):
            return {}, True
        return parsed, False
