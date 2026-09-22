"""全局快捷键模块：注册并监听 Ctrl+Alt+T / Ctrl+Alt+Z。

注意：
    回调运行在 keyboard 库的钩子线程里，不是 Qt 主线程。
    因此这里不直接操作界面，只把"动作"放进队列，
    由 main.py 的 QTimer 在主线程里取出执行（drain_actions）。
"""

from __future__ import annotations

import queue
import threading
import time

import keyboard

TRANSLATE_HOTKEY = "ctrl+alt+t"
SNIP_HOTKEY = "ctrl+alt+z"

# 组合键里的主键名，用于判断是否仍被按住
TRANSLATE_KEY = "t"
SNIP_KEY = "z"

ACTION_TRANSLATE = "translate"
ACTION_SNIP = "snip"

# 同一动作在该时间窗内的重复触发视为同一次（秒）
DEBOUNCE_SECONDS = 0.5

# 动作队列：钩子线程写入，主线程读取
_ACTIONS: "queue.Queue[str]" = queue.Queue()
_HOOKS: list = []
_RELEASE_HOOKS: list = []
_LOCK = threading.Lock()
# 每个动作上次放行的时间戳，用于去抖
_LAST_FIRED: dict = {}
# 主键当前是否仍被按住：按住期间产生的一律是键盘自动重复
_HELD: dict = {}

__all__ = [
    "TRANSLATE_HOTKEY",
    "SNIP_HOTKEY",
    "ACTION_TRANSLATE",
    "ACTION_SNIP",
    "register_hotkeys",
    "unregister_hotkeys",
    "on_translate_hotkey",
    "on_snip_hotkey",
    "wait_for_modifiers_release",
    "drain_actions",
    "clear_actions",
]


def _emit(action: str, key: str) -> None:
    """把动作放进队列，并屏蔽键盘自动重复。

    按住快捷键不放时 Windows 会持续发送 KEY_DOWN（键盘自动重复，约 30 次/秒），
    钩子回调随之被反复调用，队列里会堆积多个相同动作，
    表现为「一次操作结束后又莫名弹出一次」。

    这里用「主键是否仍被按住」来判定：按住期间产生的一律丢弃，
    只有真正松开后再按下才算新的一次触发。去抖作为第二道保险。
    """
    with _LOCK:
        if _HELD.get(key):
            return  # 仍按住 -> 自动重复
        _HELD[key] = True

    now = time.monotonic()
    with _LOCK:
        if now - _LAST_FIRED.get(action, 0.0) < DEBOUNCE_SECONDS:
            return
        _LAST_FIRED[action] = now

    _ACTIONS.put(action)


def _on_key_release(event=None) -> None:
    """主键松开：清除按住标记，使下一次按下能被正常识别。"""
    name = getattr(event, "name", None)
    if name:
        _HELD[name] = False


def on_translate_hotkey() -> None:
    """Ctrl+Alt+T：划词翻译的回调（运行在钩子线程）。"""
    _emit(ACTION_TRANSLATE, TRANSLATE_KEY)


def on_snip_hotkey() -> None:
    """Ctrl+Alt+Z：截图翻译的回调（运行在钩子线程）。"""
    _emit(ACTION_SNIP, SNIP_KEY)


def register_hotkeys(enable_snip: bool = False, trigger_on_release: bool = False) -> None:
    """注册全局快捷键。

    默认在**按下**时触发（trigger_on_release=False）。
    源码里 trigger_on_release=True 会走 KEY_UP 分支，带修饰键的组合键在该路径下常不触发，
    因此改用按下触发；"按下瞬间 Ctrl/Alt 仍被按住会导致模拟 Ctrl+C 变成 Ctrl+Alt+C"
    这个问题改由 wait_for_modifiers_release() 在取词前等待物理松开来规避。

    Args:
        enable_snip: 是否同时注册截图快捷键，默认关闭（OCR 未实现）。
        trigger_on_release: 是否在松开时触发，默认 False。

    Raises:
        Exception: keyboard 注册失败时向上抛出，由调用方提示用户。
    """
    global _HOOKS, _RELEASE_HOOKS
    with _LOCK:
        if _HOOKS:
            return
        _HOOKS.append(
            keyboard.add_hotkey(
                TRANSLATE_HOTKEY,
                on_translate_hotkey,
                trigger_on_release=trigger_on_release,
            )
        )
        if enable_snip:
            _HOOKS.append(
                keyboard.add_hotkey(
                    SNIP_HOTKEY,
                    on_snip_hotkey,
                    trigger_on_release=trigger_on_release,
                )
            )

        # 监听主键松开（按扫描码分发，不受修饰键影响），用于清除「按住」标记
        if not _RELEASE_HOOKS:
            for key in (TRANSLATE_KEY, SNIP_KEY):
                _RELEASE_HOOKS.append(keyboard.on_release_key(key, _on_key_release))


def unregister_hotkeys() -> None:
    """注销已注册的全局快捷键。"""
    global _HOOKS
    with _LOCK:
        for hook in _HOOKS:
            try:
                keyboard.remove_hotkey(hook)
            except Exception:  # noqa: BLE001
                pass
        _HOOKS.clear()

        for hook in _RELEASE_HOOKS:
            try:
                keyboard.unhook(hook)
            except Exception:  # noqa: BLE001
                pass
        _RELEASE_HOOKS.clear()


def wait_for_modifiers_release(timeout: float = 1.0) -> bool:
    """等待 Ctrl / Alt 物理松开，确保后续模拟的 Ctrl+C 不被污染成 Ctrl+Alt+C。

    Args:
        timeout: 最长等待秒数。

    Returns:
        bool: True 表示已松开，False 表示超时放弃。
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if not (keyboard.is_pressed("ctrl") or keyboard.is_pressed("alt")):
                return True
        except Exception:  # noqa: BLE001
            return False
        time.sleep(0.02)
    return False


def drain_actions() -> list[str]:
    """取出自上次调用以来积累的所有动作（供 Qt 主线程轮询）。

    Returns:
        list[str]: 动作名列表，可能为空。
    """
    actions = []
    while True:
        try:
            actions.append(_ACTIONS.get_nowait())
        except queue.Empty:
            break
    return actions


def clear_actions(action: str | None = None) -> int:
    """丢弃队列中尚未处理的动作。

    一个操作正在执行时，期间因键盘自动重复堆积的同类动作应当全部作废。
    同时重置去抖时间戳，否则刚操作完的下一次真实按键会被去抖吞掉。

    Args:
        action: 只清理该动作；None 表示清空全部。

    Returns:
        int: 被丢弃的动作数量。
    """
    dropped = 0
    kept: list[str] = []
    while True:
        try:
            item = _ACTIONS.get_nowait()
        except queue.Empty:
            break
        if action is None or item == action:
            dropped += 1
        else:
            kept.append(item)

    for item in kept:
        _ACTIONS.put(item)

    with _LOCK:
        if action is None:
            _LAST_FIRED.clear()
        else:
            _LAST_FIRED.pop(action, None)

    return dropped
