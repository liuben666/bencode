"""OpenAI 适配器

基于 OpenAI Python SDK 实现流式 Chat Completions。
支持兼容 OpenAI 协议的推理模型（DeepSeek-reasoner、OpenAI o 系列等）的思考内容输出。
支持工具调用（function calling）：
- 请求携带工具清单（tools + tool_choice="auto"）
- 流式解析 delta.tool_calls 增量：按 index 聚合调用槽位，参数 JSON 字符串碎片拼接，
  流结束后整体反序列化，产出统一的 tool_call chunk
- 消息构建支持回传 assistant 工具调用消息与 tool 角色结果消息
"""

import json
from typing import AsyncIterator, Optional

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
        - role: "user" | "assistant" | "tool" | "system"
        - content: 字符串（assistant 工具调用消息可为 None）
        - assistant 消息携带 tool_calls 数组时需原样回传
        - tool 角色消息通过 tool_call_id 关联调用

        注意：thinking_text 不传回 API。
        DeepSeek/OpenAI o 系列的推理内容是模型内部状态，
        多轮对话时只需传正文 content，不需要传推理过程。
        """
        result = []
        for msg in messages:
            if msg.role == Role.SYSTEM:
                result.append({"role": "system", "content": msg.text})
            elif msg.role == Role.USER:
                result.append({"role": "user", "content": msg.text})
            elif msg.role == Role.ASSISTANT:
                if msg.tool_calls:
                    # 工具调用消息：tool_calls 数组 + content（可为 None）
                    result.append({
                        "role": "assistant",
                        "content": msg.text or None,
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {
                                    "name": tc.name,
                                    "arguments": json.dumps(
                                        tc.arguments or {}, ensure_ascii=False
                                    ),
                                },
                            }
                            for tc in msg.tool_calls
                        ],
                    })
                else:
                    result.append({"role": "assistant", "content": msg.text})
            elif msg.role == Role.TOOL:
                # 工具结果消息：tool_call_id 关联
                result.append({
                    "role": "tool",
                    "tool_call_id": msg.tool_call_id or "",
                    "content": msg.text,
                })
        return result

    async def chat_stream(
        self,
        messages: list[MessageContent],
        tools=None,
    ) -> AsyncIterator[StreamChunk]:
        """流式发送对话请求

        使用 AsyncOpenAI 的 chat.completions.create(stream=True)，
        遍历异步迭代器，从 delta 提取增量内容。

        解析逻辑：
        - delta.reasoning_content（DeepSeek 风格）→ thinking chunk
        - delta.reasoning（OpenAI o 系列风格）→ thinking chunk
        - delta.content → text chunk
        - delta.tool_calls → 按 index 聚合，参数 JSON 碎片拼接，
          流结束后反序列化为完整参数，产出 tool_call chunk

        参考（来源：context7 MCP 查询 OpenAI 官方文档）：
        - Chat Completions tools 参数：{"type": "function", "function": {...}}
        - 流式工具调用：delta.tool_calls[].index/id/function.name/function.arguments
        - 工具结果回传：{"role": "tool", "tool_call_id": ..., "content": ...}
        """
        try:
            kwargs = {
                "model": self.config.model,
                "messages": self._build_messages(messages),
                "stream": True,
                "max_tokens": 4096,
            }
            # 思考开关（TUI 的 thinking 按钮通过 config.thinking 传递）：
            # - 关闭（config.thinking 为 None）：传 enable_thinking=False，让百练/DeepSeek 系
            #   思考模型停止输出 reasoning_content（DashScope 通用参数，经 extra_body 传入）
            # - 开启：不传参数，由模型默认行为决定（思考模型默认开启）
            # 注：仅思考模型（如 kimi/kimi-k2.7-code）会忽略该参数继续思考
            if self.config.thinking is None:
                kwargs["extra_body"] = {"enable_thinking": False}
            # 携带工具清单（收尾轮不传 tools，模型只能纯文本作答）
            if tools is not None:
                kwargs["tools"] = tools.to_openai_tools()
                kwargs["tool_choice"] = "auto"

            stream = await self._client.chat.completions.create(**kwargs)

            # 工具调用聚合器：index → {"id", "name", "arguments"}
            tool_call_acc: dict[int, dict] = {}

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

                # 聚合工具调用增量（参数 arguments 为 JSON 字符串碎片，逐片拼接）
                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        idx = tc.index if tc.index is not None else 0
                        slot = tool_call_acc.setdefault(
                            idx, {"id": "", "name": "", "arguments": ""}
                        )
                        if tc.id:
                            slot["id"] = tc.id
                        if tc.function is not None:
                            if tc.function.name:
                                slot["name"] = slot["name"] + tc.function.name
                            if tc.function.arguments:
                                slot["arguments"] += tc.function.arguments

                # 流结束标记
                if choice.finish_reason is not None:
                    break

            # 流结束：逐个产出完整的工具调用（按 index 顺序）
            for idx in sorted(tool_call_acc.keys()):
                slot = tool_call_acc[idx]
                arguments, parse_error = self._parse_tool_arguments(
                    slot["arguments"]
                )
                yield StreamChunk(
                    type="tool_call",
                    metadata={
                        "id": slot["id"] or f"call_{idx}",
                        "name": slot["name"],
                        "arguments": arguments,
                        # 参数 JSON 拼接后非法时置 True，由上层转为错误结果回灌
                        "parse_error": parse_error,
                    },
                )

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
