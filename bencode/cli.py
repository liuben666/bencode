"""BenCode CLI 入口

解析命令行参数，加载配置，启动 Textual TUI 应用。
"""

import argparse
import sys

from bencode.config.loader import load_config, ConfigError
from bencode.tui.app import BenCodeApp


def parse_args() -> argparse.Namespace:
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        prog="bencode",
        description="BenCode - 终端 AI 编程助手",
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="指定配置文件路径（默认查找顺序：./config.yaml → ~/.bencode/config.yaml）",
    )
    parser.add_argument(
        "--provider",
        type=str,
        default=None,
        help="指定 provider 配置名称，跳过选择界面",
    )
    parser.add_argument(
        "--session",
        type=str,
        default=None,
        help="恢复指定会话 ID 继续对话",
    )
    return parser.parse_args()


def main() -> None:
    """BenCode 主入口"""
    args = parse_args()

    # 加载配置
    try:
        config = load_config(config_path=args.config)
    except ConfigError as e:
        # 配置错误，打印提示并退出
        print(f"⚠️  配置错误: {e}", file=sys.stderr)
        sys.exit(1)

    # 启动 Textual TUI 应用
    app = BenCodeApp(
        config=config,
        provider_name=args.provider,
        session_id=args.session,
    )
    app.run()


if __name__ == "__main__":
    main()
