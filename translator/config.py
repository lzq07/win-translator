"""配置模块：从 .env / 环境变量读取配置（如 API Key）。

优先级：项目根目录的 .env 会覆盖系统环境变量（override=True），
这样本地调试时改 .env 一定生效，不会被残留的系统变量干扰。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# 项目根目录（translator/ 的上一级）
BASE_DIR = Path(__file__).resolve().parent.parent
ENV_PATH = BASE_DIR / ".env"
ASSETS_DIR = BASE_DIR / "assets"
ICON_PATH = ASSETS_DIR / "icon.ico"

DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_MODEL = "deepseek-chat"
DEFAULT_TIMEOUT = 30.0

# 视为“未填写”的占位值
PLACEHOLDER_KEYS = {
    "",
    "sk-your-api-key-here",
    "your-api-key",
    "changeme",
}


@dataclass
class Config:
    """运行所需的配置。"""

    api_key: str
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    timeout: float = DEFAULT_TIMEOUT

    @property
    def endpoint(self) -> str:
        """chat/completions 完整地址。"""
        return f"{self.base_url.rstrip('/')}/chat/completions"


def clean_value(value: str | None) -> str:
    """去掉首尾空白与包裹的引号（.env 里写成 "xxx" 也能正常读）。"""
    if value is None:
        return ""
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        value = value[1:-1].strip()
    return value


def load_config(override: bool = True) -> Config:
    """加载配置并做基本校验。

    Args:
        override: .env 是否覆盖已存在的同类环境变量，默认 True。

    Returns:
        Config: 校验通过的配置对象。

    Raises:
        ValueError: 未填写或仍是占位符的 API Key。
    """
    load_dotenv(ENV_PATH, override=override)

    api_key = clean_value(os.getenv("DEEPSEEK_API_KEY"))
    if api_key in PLACEHOLDER_KEYS:
        raise ValueError(
            f"未检测到有效的 DEEPSEEK_API_KEY。\n"
            f"请在 {ENV_PATH} 中填写你的真实 Key（该文件已被 .gitignore 忽略）。"
        )

    return Config(
        api_key=api_key,
        base_url=clean_value(os.getenv("DEEPSEEK_BASE_URL")) or DEFAULT_BASE_URL,
        model=clean_value(os.getenv("DEEPSEEK_MODEL")) or DEFAULT_MODEL,
        timeout=DEFAULT_TIMEOUT,
    )


def get_api_key() -> str:
    """获取 DeepSeek API Key。"""
    return load_config().api_key


def get_base_url() -> str:
    """获取 DeepSeek API 的 Base URL。"""
    return load_config().base_url
