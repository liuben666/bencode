"""YAML 配置文件加载与校验

配置文件查找顺序：
1. --config 参数显式指定的路径
2. 当前工作目录下的 config.yaml（项目级配置）
3. ~/.bencode/config.yaml（用户级配置）
"""

import os
from typing import Optional

import yaml

from bencode.config.schema import AppConfig, ProviderConfig

# 用户级配置目录（会话持久化也在此目录下）
USER_CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".bencode")
USER_CONFIG_PATH = os.path.join(USER_CONFIG_DIR, "config.yaml")

# 项目级配置文件名（当前工作目录下）
PROJECT_CONFIG_NAME = "config.yaml"

# 配置模板内容
CONFIG_TEMPLATE = """# BenCode 配置文件
# 支持多个 provider 配置，启动时可选择使用哪个

providers:
  - name: claude                    # 供应商标识名，方便区分多个配置
    protocol: anthropic             # 协议类型：anthropic / openai
    model: claude-sonnet-4-20250514 # 模型名称
    base_url: https://api.anthropic.com  # API 请求地址
    api_key: sk-ant-xxx             # 认证密钥
    # thinking:                     # 可选：启用 Claude 扩展思考
    #   type: enabled
    #   budget_tokens: 10000

  # - name: deepseek                # DeepSeek 推理模型（自动输出思考内容）
  #   protocol: openai
  #   model: deepseek-reasoner
  #   base_url: https://api.deepseek.com/v1
  #   api_key: sk-xxx

  # - name: openai                  # OpenAI o 系列推理模型
  #   protocol: openai
  #   model: o3-mini
  #   base_url: https://api.openai.com/v1
  #   api_key: sk-xxx
"""


class ConfigError(Exception):
    """配置相关错误"""


def ensure_user_config_dir() -> None:
    """确保用户级配置目录和 sessions 目录存在"""
    os.makedirs(USER_CONFIG_DIR, exist_ok=True)
    os.makedirs(os.path.join(USER_CONFIG_DIR, "sessions"), exist_ok=True)


def generate_template_config() -> str:
    """生成模板配置文件内容"""
    return CONFIG_TEMPLATE


def _find_config_path(explicit_path: Optional[str] = None) -> str:
    """按优先级查找配置文件路径

    查找顺序：
    1. explicit_path（--config 参数指定的路径）
    2. 当前工作目录下的 config.yaml
    3. ~/.bencode/config.yaml

    Returns:
        找到的配置文件路径，若都不存在则返回项目级路径（用于生成模板）
    """
    if explicit_path:
        return explicit_path

    # 项目级：当前工作目录下的 config.yaml
    project_path = os.path.join(os.getcwd(), PROJECT_CONFIG_NAME)
    if os.path.exists(project_path):
        return project_path

    # 用户级：~/.bencode/config.yaml
    if os.path.exists(USER_CONFIG_PATH):
        return USER_CONFIG_PATH

    # 都不存在，返回项目级路径（后续会在此生成模板）
    return project_path


def load_config(config_path: Optional[str] = None) -> AppConfig:
    """
    加载并校验配置文件。

    配置文件查找顺序：
    1. config_path 参数（--config 指定）
    2. 当前工作目录下的 config.yaml（项目级）
    3. ~/.bencode/config.yaml（用户级）

    若配置文件不存在，在项目目录生成模板并抛出 ConfigError 提示用户编辑。
    若配置文件存在但校验失败，抛出 ConfigError 说明具体问题。

    Args:
        config_path: 自定义配置文件路径（--config 参数）

    Returns:
        AppConfig: 解析后的应用配置对象

    Raises:
        ConfigError: 配置文件不存在、格式错误或字段校验失败
    """
    path = _find_config_path(config_path)

    if not os.path.exists(path):
        # 配置文件不存在，在项目目录生成模板
        config_dir = os.path.dirname(path)
        if config_dir:
            os.makedirs(config_dir, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(generate_template_config())
        raise ConfigError(
            f"配置文件不存在，已生成模板至: {path}\n"
            f"请编辑该文件填入您的 API 密钥后重新启动 BenCode。"
        )

    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    if not raw or not isinstance(raw, dict):
        raise ConfigError(f"配置文件格式错误: {path}，期望顶层为 YAML 映射")

    raw_providers = raw.get("providers")
    if not raw_providers or not isinstance(raw_providers, list):
        raise ConfigError(
            f"配置文件缺少 [providers] 列表，或列表为空。"
            f"请至少配置一个 provider。"
        )

    providers = []
    for i, item in enumerate(raw_providers):
        if not isinstance(item, dict):
            raise ConfigError(f"providers[{i}] 格式错误，期望为 YAML 映射")
        try:
            pc = ProviderConfig(
                name=item.get("name", ""),
                protocol=item.get("protocol", ""),
                model=item.get("model", ""),
                base_url=item.get("base_url", ""),
                api_key=item.get("api_key", ""),
                thinking=item.get("thinking"),
            )
            providers.append(pc)
        except ValueError as e:
            raise ConfigError(f"providers[{i}] 校验失败: {e}") from e

    # 检查 name 唯一性
    names = [p.name for p in providers]
    duplicates = [n for n in names if names.count(n) > 1]
    if duplicates:
        unique_dups = sorted(set(duplicates))
        raise ConfigError(f"provider name 重复: {', '.join(unique_dups)}")

    return AppConfig(providers=providers)
