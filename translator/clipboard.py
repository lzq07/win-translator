"""剪贴板模块：读取当前选中的文字。

划词取词思路：
    模拟按下 Ctrl+C 把选中内容复制到剪贴板 -> 轮询读取 -> 还原原剪贴板内容。
"""

from __future__ import annotations

import time

import keyboard
import pyperclip

# 等待目标程序把选中内容写进剪贴板的超时时间（秒）
COPY_TIMEOUT = 0.8
# 轮询间隔（秒）
POLL_INTERVAL = 0.02


def _safe_paste() -> str:
    """读取剪贴板，任何异常（如剪贴板中是图片）都退化为空字符串。"""
    try:
        return pyperclip.paste() or ""
    except Exception:  # noqa: BLE001 - 剪贴板内容不可控，需兜底
        return ""


def _safe_copy(text: str) -> bool:
    """写入剪贴板，失败返回 False。"""
    try:
        pyperclip.copy(text)
        return True
    except Exception:  # noqa: BLE001
        return False


def wait_for_clipboard_change(baseline: str = "", timeout: float = COPY_TIMEOUT) -> str:
    """轮询等待剪贴板内容变为非空且不同于 baseline。

    Args:
        baseline: 起始内容，用于判断"确实发生了变化"。
        timeout: 最长等待秒数。

    Returns:
        str: 新内容；超时则为空字符串。
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        current = _safe_paste()
        if current and current != baseline:
            return current
        time.sleep(POLL_INTERVAL)
    return ""


def get_selected_text(
    timeout: float = COPY_TIMEOUT,
    restore: bool = True,
    settle: float = 0.05,
) -> str:
    """获取当前选中的文本。

    Args:
        timeout: 等待复制完成的秒数。
        restore: 是否把剪贴板还原成取词前的内容。
        settle: 发送 Ctrl+C 前的静置时间，等目标程序稳定。

    Returns:
        str: 选中的文本；未取到则为空字符串。
    """
    original = _safe_paste()

    # 先清空，便于判断"是否真的写入了新内容"
    _safe_copy("")
    time.sleep(settle)

    keyboard.send("ctrl+c")
    text = wait_for_clipboard_change(baseline=original, timeout=timeout)

    if restore:
        _safe_copy(original)

    return text.strip()


def copy_text(text: str) -> bool:
    """把文本写入剪贴板。

    Args:
        text: 待写入的文本。

    Returns:
        bool: 是否成功。
    """
    return _safe_copy(text)
