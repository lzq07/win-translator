"""程序入口：启动划词 & 截图翻译工具。

功能：
    Ctrl+Alt+T —— 划词翻译（选中文字后按下，弹出置顶译文窗口）
    Ctrl+Alt+Z —— 截图翻译：
        第一次按下   进入框选模式，拖拽出选区
        调整选区     拖动选区内部可移动，拖动 8 个手柄可改大小
        再次按 Z     确认，开始 OCR + 翻译
        Esc / 右键   取消
"""

from __future__ import annotations

import sys

from PyQt6.QtCore import QRect, QTimer
from PyQt6.QtWidgets import QApplication

from translator import clipboard, hotkey, translate as translate_api
from translator.config import load_config
from translator.ocr import grab_region, ocr_image
from translator.ui import ResultWindow, SnipOverlay, ensure_app

# 轮询快捷键动作队列的间隔（毫秒）
POLL_INTERVAL_MS = 80
# 遮罩隐藏后等画面刷新再抓取的延迟（毫秒）
GRAB_DELAY_MS = 80
# 单实例互斥体名
MUTEX_NAME = "Global\\win_translator_single_instance"
_mutex_handle = None


def _acquire_single_instance() -> bool:
    """用命名互斥体保证只有一个实例在运行。

    多个实例会各自注册一份全局快捷键，表现为「按一次触发多次」，必须挡住。

    Returns:
        bool: True 表示本进程是唯一实例；False 表示已有实例在运行。
    """
    if sys.platform != "win32":
        return True

    import ctypes

    global _mutex_handle
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    kernel32.CreateMutexW.argtypes = [
        ctypes.c_void_p,
        ctypes.c_int,
        ctypes.c_wchar_p,
    ]

    handle = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if not handle:
        return True  # 创建失败就不拦截，避免误伤
    if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
        return False
    _mutex_handle = handle  # 保活，进程退出时才释放
    return True


class TranslatorApp:
    """把快捷键、取词/框选、翻译、弹窗串起来的应用对象。"""

    def __init__(self):
        self.config = load_config()
        self.window = ResultWindow()
        self.timer = QTimer()
        self.timer.timeout.connect(self._poll_actions)
        # 当前框选会话的遮罩；None 表示没有在框选
        self._overlay: SnipOverlay | None = None
        # 正在 OCR / 翻译，期间忽略新的截图请求
        self._processing = False

    # ---------- 生命周期 ----------

    def start(self) -> None:
        """注册快捷键并启动轮询。"""
        hotkey.register_hotkeys(enable_snip=True)
        self.timer.start(POLL_INTERVAL_MS)

    def stop(self) -> None:
        """停止轮询并注销快捷键。"""
        self.timer.stop()
        hotkey.unregister_hotkeys()

    # ---------- 主线程轮询 ----------

    def _poll_actions(self) -> None:
        """在主线程里消费钩子线程投递的动作。"""
        handled = set()
        for action in hotkey.drain_actions():
            # 同一次轮询里相同动作只处理一次
            if action in handled:
                continue
            handled.add(action)

            if action == hotkey.ACTION_TRANSLATE:
                self.run_selection_translate()
            elif action == hotkey.ACTION_SNIP:
                self.on_snip_trigger()

            # 本次触发已消费：清掉同时堆积的重复，并重置去抖时间戳
            hotkey.clear_actions(action)

    # ---------- 划词翻译 ----------

    def run_selection_translate(self) -> None:
        """划词翻译：取词 -> 调 API -> 弹窗显示。"""
        # 等修饰键物理松开，避免 Ctrl+C 被污染成 Ctrl+Alt+C
        hotkey.wait_for_modifiers_release()

        text = clipboard.get_selected_text()
        if not text:
            self.window.show_result("", "没有获取到选中的文字，请先选中再按快捷键。")
            return

        self.window.show_result(text, "翻译中…")
        QApplication.processEvents()
        self.window.show_result(text, self._translate(text))

    # ---------- 截图翻译 ----------

    def on_snip_trigger(self) -> None:
        """Ctrl+Alt+Z 的统一入口：没有遮罩就开遮罩，已有遮罩就确认。"""
        if self._overlay is not None:
            if not self._overlay.confirm():
                print("[snip] 还没有有效选区，请先拖拽出一个区域。")
            return

        if self._processing:
            return

        overlay = SnipOverlay(confirm_on_release=False)
        overlay.confirmed.connect(self._on_region_confirmed)
        overlay.canceled.connect(self._close_overlay)
        self._overlay = overlay
        overlay.start()

    def _close_overlay(self) -> None:
        """关闭并销毁当前遮罩。"""
        overlay = self._overlay
        self._overlay = None
        if overlay is not None:
            overlay.hide()
            overlay.deleteLater()

    def _on_region_confirmed(self, rect: QRect) -> None:
        """选区确认：先收起遮罩，等画面刷新后再抓取。"""
        self._close_overlay()
        self._processing = True
        QApplication.processEvents()
        QTimer.singleShot(GRAB_DELAY_MS, lambda: self._process_region(rect))

    def _process_region(self, rect: QRect) -> None:
        """抓取选区 -> OCR -> 翻译 -> 弹窗。"""
        try:
            image = grab_region(rect)
            text = ocr_image(image)
            if not text:
                self.window.show_result(
                    "", "没有识别到文字。框大一些，或把页面放大再试。"
                )
                return

            self.window.show_result(text, "翻译中…")
            QApplication.processEvents()
            self.window.show_result(text, self._translate(text))
        except Exception as exc:  # noqa: BLE001 - 需要把错误显示给用户
            print(f"[snip] 流程失败：{exc}")
            self.window.show_result("", f"截图翻译失败：{exc}")
        finally:
            self._processing = False

    # ---------- 公共 ----------

    def _translate(self, text: str) -> str:
        """调用翻译接口，把异常转成可展示的文本。"""
        try:
            return translate_api.translate(text, self.config)
        except Exception as exc:  # noqa: BLE001
            return f"翻译失败：{exc}"


def main() -> int:
    """初始化配置与界面，注册快捷键并进入事件循环。"""
    if not _acquire_single_instance():
        print("[main] 已有一个实例在运行，请勿重复启动（重复启动会让快捷键触发多次）。")
        return 1

    try:
        config = load_config()
    except ValueError as exc:
        print(f"[config] {exc}")
        return 1

    app = ensure_app()
    app.setQuitOnLastWindowClosed(False)

    translator_app = TranslatorApp()
    try:
        translator_app.start()
    except Exception as exc:  # noqa: BLE001
        print(f"[hotkey] 注册快捷键失败：{exc}")
        print("提示：若目标程序以管理员身份运行，请用管理员权限的终端启动本程序。")
        return 1

    app.aboutToQuit.connect(translator_app.stop)

    masked = (
        f"{config.api_key[:7]}...{config.api_key[-4:]}"
        if len(config.api_key) > 11
        else "***"
    )
    print(f"[ready] 已就绪 | model={config.model} | key={masked}")
    print("[ready] Ctrl+Alt+T 划词翻译。")
    print("[ready] Ctrl+Alt+Z 框选：拖出选区 -> 可拖动/缩放调整 -> 再按一次 Z 识别翻译。")
    print("[ready] 框选时 Esc / 右键取消；退出：在本终端按 Ctrl+C。")

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
