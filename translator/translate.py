"""翻译模块：调用 DeepSeek API (OpenAI 兼容) 完成翻译。"""

from __future__ import annotations

import httpx

from .config import Config, load_config

# 翻译用的系统提示词
SYSTEM_PROMPT = (
    "你是一个专业的翻译引擎。\n"
    "规则：\n"
    "1. 如果用户输入是英文或其他外文，翻译成简体中文；\n"
    "2. 如果用户输入是中文，翻译成英文；\n"
    "3. 只输出译文本身，不要解释、不要注释、不要加引号或任何多余文字；\n"
    "4. 保留原文的段落与换行结构。"
)

__all__ = ["SYSTEM_PROMPT", "build_payload", "translate"]


def build_payload(text: str, model: str) -> dict:
    """构造请求 DeepSeek 接口的 payload。

    Args:
        text: 待翻译的文本。
        model: 模型名称。

    Returns:
        dict: 可直接作为 JSON 请求体的字典。
    """
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
        "temperature": 0.3,
        "stream": False,
    }


def translate(text: str, config: Config | None = None) -> str:
    """调用 DeepSeek API 翻译文本。

    Args:
        text: 待翻译的文本。
        config: 配置对象；为 None 时自动从 .env 加载。

    Returns:
        str: 译文。

    Raises:
        ValueError: 文本为空。
        RuntimeError: 网络失败、接口返回非 200 或响应结构异常。
    """
    text = (text or "").strip()
    if not text:
        raise ValueError("待翻译文本为空。")

    cfg = config or load_config()

    headers = {
        "Authorization": f"Bearer {cfg.api_key}",
        "Content-Type": "application/json",
    }

    try:
        response = httpx.post(
            cfg.endpoint,
            json=build_payload(text, cfg.model),
            headers=headers,
            timeout=cfg.timeout,
        )
    except httpx.HTTPError as exc:
        raise RuntimeError(f"请求 DeepSeek 失败：{exc}") from exc

    if response.status_code != 200:
        raise RuntimeError(
            f"DeepSeek 返回 HTTP {response.status_code}：{response.text[:500]}"
        )

    try:
        data = response.json()
        return data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise RuntimeError(f"响应解析失败：{response.text[:500]}") from exc
