"""OpenAI 适配器

基于 OpenAI Python SDK 实现流式 Chat Completions。
支持兼容 OpenAI 协议的推理模型（DeepSeek-reasoner、OpenAI o 系列等）的思考内容输出。
"""

from typing import AsyncIterator

import openai

from bencode.config.schema import ProviderConfig
from bencode.provider.base import BaseProvider, MessageContent, Role, StreamChunk, ProviderError


class OpenAIProvider(BaseProvider):
    """OpenAI 后端适配器

    使用 AsyncOpenAI 客户端，通过 stream=True 开启流式 Chat Completions。
    遍历异步迭代器，从每个 chunk 的 choices[0].delta 提取增量内容。

    支持推理模型的思考内容输出：
    - DeepSeek reasoner：通过 delta.reasoning_content 字段返回推理内容
    - OpenAI o 系列：通过 delta.reasoning 字段返回推理内容
    - 其他兼容 OpenAI 协议的推理模型同理

    推理内容作为 thinking 类型的 StreamChunk 返回，在 TUI 中以折叠区块展示。
    多轮对话时，历史 thinking 内容不传回 API（OpenAI 协议不需要）。
    """

    def __init__(self, config: ProviderConfig) -> None:
        super().__init__(config)
        self._client = openai.AsyncOpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
        )

    @property
    def provider_name(self) -> str:
        return f"OpenAI ({self.config.name})"

    @property
    def model_name(self) -> str:
        return self.config.model

    def _build_messages(self, messages: list[MessageContent]) -> list[dict]:
        """将统一消息格式转换为 OpenAI Chat Completions 所需格式

        OpenAI 消息格式：
        - role: "user" | "assistant" | "system"
        - content: 字符串

        注意：thinking_text 不传回 API。
        DeepSeek/OpenAI o 系列的推理内容是模型内部状态，
        多轮对话时只需传正文 content，不需要传推理过程。
        """
        result = []
        for msg in messages:
            result.append({
                "role": msg.role.value,
                "content": msg.text,
            })
        return result

    async def chat_stream(
        self,
        messages: list[MessageContent],
    ) -> AsyncIterator[StreamChunk]:
        """流式发送对话请求

        使用 AsyncOpenAI 的 chat.completions.create(stream=True)，
        遍历异步迭代器，从 delta 提取增量内容。

        解析逻辑：
        - delta.reasoning_content（DeepSeek 风格）→ thinking chunk
        - delta.reasoning（OpenAI o 系列风格）→ thinking chunk
        - delta.content → text chunk

        参考：
        - OpenAI Python SDK 官方文档（Chat Completions streaming）
        - DeepSeek API 文档（deepseek-reasoner 模型的 reasoning_content 字段）
        """
        try:
            stream = await self._client.chat.completions.create(
                model=self.config.model,
                messages=self._build_messages(messages),
                stream=True,
                max_tokens=4096,
            )

            async for chunk in stream:
                if not chunk.choices:
                    # 最后一个 chunk（stream_options={"include_usage": True} 时可能为空）
                    continue

                choice = chunk.choices[0]
                delta = choice.delta

                # 提取推理内容（DeepSeek 风格：reasoning_content）
                reasoning_content = getattr(delta, "reasoning_content", None)
                if reasoning_content is not None:
                    yield StreamChunk(
                        type="thinking",
                        text=reasoning_content,
                    )

                # 提取推理内容（OpenAI o 系列风格：reasoning）
                reasoning = getattr(delta, "reasoning", None)
                if reasoning is not None:
                    yield StreamChunk(
                        type="thinking",
                        text=reasoning,
                    )

                # 提取正文文本内容
                if delta.content is not None:
                    yield StreamChunk(
                        type="text",
                        text=delta.content,
                    )

                # 流结束标记
                if choice.finish_reason is not None:
                    break

            # 流结束
            yield StreamChunk(type="done")

        except openai.APIConnectionError as e:
            raise ProviderError(f"OpenAI API 连接失败: {e}") from e
        except openai.RateLimitError as e:
            raise ProviderError(f"OpenAI API 请求频率超限: {e}") from e
        except openai.APIStatusError as e:
            raise ProviderError(
                f"OpenAI API 错误 (状态码 {e.status_code}): {e.message}"
            ) from e
        except Exception as e:
            raise ProviderError(f"OpenAI API 未知错误: {e}") from e
