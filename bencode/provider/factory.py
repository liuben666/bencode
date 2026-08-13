"""Provider 工厂与注册机制

根据配置中的 protocol 字段自动创建对应的 Provider 实例。
新增后端只需：1. 实现 BaseProvider 接口  2. 在 _PROTOCOL_MAP 中注册
"""

from bencode.config.schema import ProviderConfig
from bencode.provider.base import BaseProvider
from bencode.provider.anthropic import AnthropicProvider
from bencode.provider.openai import OpenAIProvider

# 协议字符串 → 适配器类映射
_PROTOCOL_MAP: dict[str, type[BaseProvider]] = {
    "anthropic": AnthropicProvider,
    "openai": OpenAIProvider,
}


class ProviderFactoryError(Exception):
    """Provider 工厂错误"""


def create_provider(config: ProviderConfig) -> BaseProvider:
    """根据配置创建 Provider 实例

    Args:
        config: Provider 配置对象

    Returns:
        BaseProvider: 对应协议的适配器实例

    Raises:
        ProviderFactoryError: 协议不支持时抛出
    """
    provider_cls = _PROTOCOL_MAP.get(config.protocol)
    if provider_cls is None:
        supported = ", ".join(_PROTOCOL_MAP.keys())
        raise ProviderFactoryError(
            f"不支持的协议类型: {config.protocol}，"
            f"当前支持的协议: {supported}"
        )
    return provider_cls(config)


def register_protocol(protocol: str, provider_cls: type[BaseProvider]) -> None:
    """注册新的协议类型

    扩展后端时调用此函数注册，无需修改工厂代码。

    Args:
        protocol: 协议标识字符串
        provider_cls: 实现了 BaseProvider 的适配器类
    """
    _PROTOCOL_MAP[protocol] = provider_cls
