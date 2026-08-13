"""配置数据模型定义"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ProviderConfig:
    """单个 LLM Provider 的配置项"""

    name: str  # 供应商标识名，方便区分多个配置
    protocol: str  # 决定走哪家协议（anthropic / openai）
    model: str  # 指定模型
    base_url: str  # 指定请求的地址
    api_key: str  # 做认证
    thinking: Optional[dict] = None  # 是否启用扩展思考，可选（如 {"type": "enabled", "budget_tokens": 10000}）

    # 支持的协议类型
    VALID_PROTOCOLS = ("anthropic", "openai")

    def __post_init__(self):
        """校验必填字段和协议合法性"""
        if not self.name:
            raise ValueError("配置字段 [name] 不能为空")
        if not self.protocol:
            raise ValueError("配置字段 [protocol] 不能为空")
        if self.protocol not in self.VALID_PROTOCOLS:
            raise ValueError(
                f"配置字段 [protocol] 值无效: {self.protocol}，"
                f"可选值: {', '.join(self.VALID_PROTOCOLS)}"
            )
        if not self.model:
            raise ValueError(f"provider [{self.name}] 配置字段 [model] 不能为空")
        if not self.base_url:
            raise ValueError(f"provider [{self.name}] 配置字段 [base_url] 不能为空")
        if not self.api_key:
            raise ValueError(f"provider [{self.name}] 配置字段 [api_key] 不能为空")


@dataclass
class AppConfig:
    """BenCode 应用总配置"""

    providers: list[ProviderConfig] = field(default_factory=list)

    def get_provider(self, name: str) -> Optional[ProviderConfig]:
        """按名称查找 Provider 配置"""
        for p in self.providers:
            if p.name == name:
                return p
        return None
