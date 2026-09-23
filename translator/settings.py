"""用户设置：读写 %APPDATA%\\WinTranslator\\settings.json。

这是给最终用户用的配置方式，不需要手动编辑 .env。
优先级：**用户设置文件 > .env > 默认值**（.env 主要用于开发调试）。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from .config import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    DEFAULT_TIMEOUT,
    ENV_PATH,
    PLACEHOLDER_KEYS,
    Config,
    clean_value,
    load_config,
)
from .hotkey import DEFAULT_SNIP_HOTKEY, DEFAULT_TRANSLATE_HOTKEY

APP_DIR_NAME = "WinTranslator"
SETTINGS_FILENAME = "settings.json"

# 设置界面里给出的模型候选（下拉框允许自己填别的）
SUGGESTED_MODELS = ("deepseek-chat", "deepseek-reasoner")

# 设置文件的字段与默认值
DEFAULTS: dict = {
    "api_key": "",
    "base_url": DEFAULT_BASE_URL,
    "model": DEFAULT_MODEL,
    "timeout": DEFAULT_TIMEOUT,
    "hotkey_translate": DEFAULT_TRANSLATE_HOTKEY,
    "hotkey_snip": DEFAULT_SNIP_HOTKEY,
}

__all__ = [
    "DEFAULTS",
    "SUGGESTED_MODELS",
    "build_config",
    "load_effective_config",
    "load_user_settings",
    "save_user_settings",
    "settings_path",
    "user_config_dir",
]


def user_config_dir() -> Path:
    """用户配置目录（Windows 下为 %APPDATA%\\WinTranslator）。"""
    base = os.getenv("APPDATA")
    if base:
        return Path(base) / APP_DIR_NAME
    return Path.home() / f".{APP_DIR_NAME.lower()}"


def settings_path() -> Path:
    """设置文件的完整路径。"""
    return user_config_dir() / SETTINGS_FILENAME


def load_user_settings() -> dict:
    """读取用户设置。

    文件不存在、内容损坏或字段缺失时，一律回退到默认值。

    Returns:
        dict: 含 api_key / base_url / model / timeout 的字典。
    """
    data = dict(DEFAULTS)
    try:
        raw = json.loads(settings_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return data

    if not isinstance(raw, dict):
        return data

    for key in DEFAULTS:
        value = raw.get(key)
        if value not in (None, ""):
            data[key] = value
    return data


def save_user_settings(data: dict) -> Path:
    """保存用户设置（只保留已知字段）。

    Args:
        data: 待保存的设置字典。

    Returns:
        Path: 实际写入的文件路径。
    """
    payload = dict(DEFAULTS)
    payload.update({k: v for k, v in data.items() if k in DEFAULTS})
    try:
        payload["timeout"] = float(payload.get("timeout") or DEFAULT_TIMEOUT)
    except (TypeError, ValueError):
        payload["timeout"] = DEFAULT_TIMEOUT

    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def build_config(data: dict) -> Config | None:
    """把设置字典转成 Config。

    Args:
        data: 设置字典。

    Returns:
        Config | None: 未填写有效 API Key 时返回 None。
    """
    api_key = clean_value(str(data.get("api_key") or ""))
    if api_key in PLACEHOLDER_KEYS:
        return None

    try:
        timeout = float(data.get("timeout") or DEFAULT_TIMEOUT)
    except (TypeError, ValueError):
        timeout = DEFAULT_TIMEOUT

    return Config(
        api_key=api_key,
        base_url=clean_value(str(data.get("base_url") or "")) or DEFAULT_BASE_URL,
        model=clean_value(str(data.get("model") or "")) or DEFAULT_MODEL,
        timeout=timeout,
    )


def load_effective_config() -> Config:
    """按「用户设置 > .env」的顺序加载配置。

    Returns:
        Config: 有效配置。

    Raises:
        ValueError: 两处都没有填写有效的 API Key。
    """
    config = build_config(load_user_settings())
    if config is not None:
        return config

    try:
        return load_config()
    except ValueError as exc:
        raise ValueError(
            "还没有配置 API Key，请在设置窗口里填写并保存。\n"
            f"设置文件位置：{settings_path()}\n"
            f"（也可以在 {ENV_PATH} 中填写，仅用于开发调试）"
        ) from exc
