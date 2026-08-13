"""Anthropic Claude 适配器

基于 Anthropic Python SDK 实现流式对话与 extended thinking。

关键 API 参考（来源：context7 MCP 查询 Anthropic Python SDK 官方文档）：
- 异步流式：AsyncAnthropic().messages.stream() 上下文管理器
- Extended thinking：请求参数 thinking={"type": "enabled", "budget_tokens": N}
- 流式事件类型：thinking / text（MessageStream 高层封装）
- 多轮 thinking 传递：需将 thinking block（含 signature）原样回传
"""

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
        # 保存最近一次 assistant 回复的 thinking signature（多轮传递用）
        self._last_thinking_signature: Optional[str] = None

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
          （多轮对话时需包含 signature 字段以保证推理链连续性）
        """
        result = []
        for msg in messages:
            if msg.role == Role.USER:
                result.append({"role": "user", "content": msg.text})
            elif msg.role == Role.ASSISTANT:
                content_blocks = []
                # 如果有 thinking 内容，需要作为 thinking block 传入
                if msg.thinking_text:
                    thinking_block: dict = {
                        "type": "thinking",
                        "thinking": msg.thinking_text,
                    }
                    # 如果有保存的 signature，加入以保持多轮推理连续性
                    if hasattr(msg, '_thinking_signature') and msg._thinking_signature:
                        thinking_block["signature"] = msg._thinking_signature
                    content_blocks.append(thinking_block)
                content_blocks.append({"type": "text", "text": msg.text})
                result.append({"role": "assistant", "content": content_blocks})
        return result

    async def chat_stream(
        self,
        messages: list[MessageContent],
    ) -> AsyncIterator[StreamChunk]:
        """流式发送对话请求

        使用 AsyncAnthropic 的 messages.stream() 上下文管理器，
        遍历流式事件，将 thinking 和 text 事件转换为统一的 StreamChunk。

        参考：Anthropic Python SDK 官方示例
        - thinking 事件：event.type == "thinking"，event.thinking 获取思考增量
        - text 事件：event.type == "text"，event.text 获取正文增量
        - content_block_stop 事件：可获取完整 content_block（含 signature）

        对于 thinking block，SDK 的 MessageStream 高层封装：
        - event.type == "thinking" 时，event.thinking 为增量文本
        - 流结束后可通过 get_final_message() 获取完整 thinking block（含 signature）
        """
        try:
            # 构建请求参数
            kwargs = {
                "model": self.config.model,
                "max_tokens": 4096,
                "messages": self._build_messages(messages),
            }

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

            thinking_accumulated = ""  # 累积完整 thinking 文本
            text_accumulated = ""  # 累积完整正文文本

            async with self._client.messages.stream(**kwargs) as stream:
                async for event in stream:
                    if event.type == "thinking":
                        # 思考内容增量
                        thinking_accumulated += event.thinking
                        yield StreamChunk(
                            type="thinking",
                            text=event.thinking,
                        )
                    elif event.type == "text":
                        # 正文内容增量
                        text_accumulated += event.text
                        yield StreamChunk(
                            type="text",
                            text=event.text,
                        )
                    elif event.type == "content_block_stop":
                        # 内容块结束时，检查是否是 thinking block 以获取 signature
                        if hasattr(event, "content_block") and event.content_block:
                            block = event.content_block
                            if hasattr(block, "type") and block.type == "thinking":
                                # 保存 signature 用于多轮对话
                                if hasattr(block, "signature"):
                                    self._last_thinking_signature = block.signature

            # 流结束
            yield StreamChunk(type="done")

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
