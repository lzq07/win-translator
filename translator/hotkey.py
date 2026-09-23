"""全局快捷键模块：注册并监听划词 / 截图两组快捷键。

组合键可在设置界面里自定义，`register_hotkeys()` 会先注销旧的再注册新的，
因此改完设置可以直接调用它让新快捷键立即生效。

注意：
    回调运行在 keyboard 库的钩子线程里，不是 Qt 主线程。
    因此这里不直接操作界面，只把「动作」放进队列，
    由 main.py 的 QTimer 在主线程里取出执行（drain_actions）。
"""

from __future__ import annotations

import queue
import threading
import time

import keyboard

DEFAULT_TRANSLATE_HOTKEY = "ctrl+alt+t"
DEFAULT_SNIP_HOTKEY = "ctrl+alt+z"

ACTION_TRANSLATE = "translate"
ACTION_SNIP = "snip"

# 认为是修饰键的名字
MODIFIER_NAMES = {"ctrl", "control", "alt", "shift", "windows", "win", "cmd"}

# 组合键最多允许的片段数（含主键）
MAX_HOTKEY_PARTS = 4

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
# 当前生效的组合键
_CURRENT: dict = {
    ACTION_TRANSLATE: DEFAULT_TRANSLATE_HOTKEY,
    ACTION_SNIP: DEFAULT_SNIP_HOTKEY,
}

__all__ = [
    "ACTION_SNIP",
    "ACTION_TRANSLATE",
    "DEFAULT_SNIP_HOTKEY",
    "DEFAULT_TRANSLATE_HOTKEY",
    "MODIFIER_NAMES",
    "clear_actions",
    "current_hotkeys",
    "drain_actions",
    "register_hotkeys",
    "unregister_hotkeys",
    "validate_hotkey",
    "wait_for_modifiers_release",
]


# ---------- 组合键校验 ----------


def validate_hotkey(text: str) -> str | None:
    """检查组合键字符串是否可用。

    Args:
        text: 形如 "ctrl+alt+t" 的组合键。

    Returns:
        str | None: 合法时返回 None，否则返回错误说明。
    """
    value = (text or "").strip().lower()
    if not value:
        return "不能为空。"
    if "," in value:
        return "不支持多段组合键（不能包含逗号）。"

    parts = [p.strip() for p in value.split("+") if p.strip()]
    if len(parts) < 2:
        return "至少需要一个修饰键，例如 ctrl+alt+t。"
    if len(parts) > MAX_HOTKEY_PARTS:
        return f"最多 {MAX_HOTKEY_PARTS} 个键。"
    if not any(p in MODIFIER_NAMES for p in parts[:-1]):
        return "至少要有一个修饰键（ctrl / alt / shift），否则会干扰正常打字。"
    if parts[-1] in MODIFIER_NAMES:
        return "最后一位必须是普通按键，不能是修饰键。"

    try:
        keyboard.parse_hotkey(value)
    except Exception as exc:  # noqa: BLE001 - 库内部抛的异常类型不固定
        # keyboard 抛的异常 args 可能是个元组，取出第一条更干净
        detail = exc.args[0] if getattr(exc, "args", None) else exc
        return f"无法识别的按键：{detail}"
    return None


def _main_key(hotkey_text: str) -> str:
    """取出组合键里的主键名，用于跟踪是否仍被按住。"""
    return hotkey_text.split("+")[-1].strip().lower()


def current_hotkeys() -> dict:
    """返回当前生效的组合键。"""
    return dict(_CURRENT)


# ---------- 队列与事件 ----------


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


def _make_callback(action: str, key: str):
    """生成绑定到具体动作与主键的回调。"""

    def callback() -> None:
        _emit(action, key)

    return callback


# ---------- 注册 / 注销 ----------


def _register_one(action: str, hotkey_text: str, trigger_on_release: bool) -> None:
    """注册单个组合键，并挂上主键的松开监听。"""
    key = _main_key(hotkey_text)
    _HOOKS.append(
        keyboard.add_hotkey(
            hotkey_text,
            _make_callback(action, key),
            trigger_on_release=trigger_on_release,
        )
    )
    _RELEASE_HOOKS.append(keyboard.on_release_key(key, _on_key_release))


def register_hotkeys(
    translate_hotkey: str = DEFAULT_TRANSLATE_HOTKEY,
    snip_hotkey: str = DEFAULT_SNIP_HOTKEY,
    enable_snip: bool = True,
    trigger_on_release: bool = False,
) -> None:
    """注册全局快捷键（会先注销已有注册，可直接用于改键后生效）。

    Args:
        translate_hotkey: 划词翻译组合键。
        snip_hotkey: 截图翻译组合键。
        enable_snip: 是否注册截图快捷键。
        trigger_on_release: 是否在松开时触发，默认按下即触发。

    Raises:
        ValueError: 组合键格式不合法。
        Exception: keyboard 库注册失败（例如没有权限）。
    """
    for label, value in (
        ("划词翻译", translate_hotkey),
        ("截图翻译", snip_hotkey),
    ):
        error = validate_hotkey(value)
        if error:
            raise ValueError(f"{label}快捷键「{value}」不合法：{error}")

    unregister_hotkeys()

    with _LOCK:
        _CURRENT[ACTION_TRANSLATE] = translate_hotkey.strip().lower()
        _CURRENT[ACTION_SNIP] = snip_hotkey.strip().lower()
        _register_one(ACTION_TRANSLATE, translate_hotkey, trigger_on_release)
        if enable_snip:
            _register_one(ACTION_SNIP, snip_hotkey, trigger_on_release)


def unregister_hotkeys() -> None:
    """注销已注册的全局快捷键。"""
    global _HOOKS, _RELEASE_HOOKS
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

        # 主键可能已经变了，清空按住标记重新开始
        _HELD.clear()


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


# ---------- 供主线程消费 ----------


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
