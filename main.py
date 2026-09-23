"""程序入口：启动划词 & 截图翻译工具。

功能：
    Ctrl+Alt+T —— 划词翻译（选中文字后按下，弹出置顶译文窗口）
    Ctrl+Alt+Z —— 截图翻译：
        第一次按下   进入框选模式，拖拽出选区
        调整选区     拖动选区内部可移动，拖动 8 个手柄可改大小
        再次按 Z     确认，开始 OCR + 翻译
        Esc / 右键   取消
    托盘图标   —— 设置 / 手动触发 / 退出

配置来源：用户设置文件（%APPDATA%\\WinTranslator\\settings.json）优先，
没有则回退到开发用的 .env。首次启动若未配置会直接弹出设置窗口。
"""

from __future__ import annotations

import sys
from dataclasses import replace

from PyQt6.QtCore import QRect, QTimer
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication, QSystemTrayIcon

from translator import clipboard, hotkey, translate as translate_api
from translator.config import ICON_PATH
from translator.ocr import grab_region, ocr_image
from translator.settings import (
    build_config,
    load_effective_config,
    load_user_settings,
)
from translator.ui import (
    APP_TITLE,
    ResultWindow,
    SettingsWindow,
    SnipOverlay,
    TrayIcon,
    ensure_app,
)

# 轮询快捷键动作队列的间隔（毫秒）
POLL_INTERVAL_MS = 80
# 遮罩隐藏后等画面刷新再抓取的延迟（毫秒）
GRAB_DELAY_MS = 80
# 测试连接时的超时上限（秒），避免设置界面卡太久
TEST_TIMEOUT = 15.0
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


def _load_icon() -> QIcon:
    """加载应用图标；文件缺失时返回空图标（Qt 会用默认图）。"""
    if ICON_PATH.exists():
        return QIcon(str(ICON_PATH))
    return QIcon()


class TranslatorApp:
    """把快捷键、取词/框选、翻译、弹窗和托盘串起来的应用对象。"""

    def __init__(self, app: QApplication, config=None):
        """
        Args:
            app: QApplication 实例。
            config: 初始配置；为 None 表示尚未配置好 API Key。
        """
        self._app = app
        self.config = config

        self.window = ResultWindow()
        self.settings_window = SettingsWindow(test_callback=self.test_connection)
        self.settings_window.saved.connect(self._on_settings_saved)

        self.tray: TrayIcon | None = None
        self.timer = QTimer()
        self.timer.timeout.connect(self._poll_actions)
        # 当前框选会话的遮罩；None 表示没有在框选
        self._overlay: SnipOverlay | None = None
        # 正在 OCR / 翻译，期间忽略新的截图请求
        self._processing = False
        # 上一次注册成功的快捷键，用于改键失败时回滚
        self._last_good_hotkeys: dict | None = None

    # ---------- 生命周期 ----------

    def start(self) -> None:
        """按当前设置注册快捷键并启动轮询。"""
        self.apply_hotkeys(load_user_settings())
        self.timer.start(POLL_INTERVAL_MS)

    def stop(self) -> None:
        """停止轮询、注销快捷键、收起托盘。"""
        self.timer.stop()
        hotkey.unregister_hotkeys()
        if self.tray is not None:
            self.tray.hide()

    def apply_hotkeys(self, data: dict) -> bool:
        """按设置注册（或重新注册）全局快捷键。

        注册内部会先注销旧组合，所以新组合若失败会回滚到上一次可用的组合，
        避免「改键失败后一个快捷键都不剩」。

        Args:
            data: 设置字典，读取其中的 hotkey_translate / hotkey_snip。

        Returns:
            bool: 是否注册成功。
        """
        wanted = {
            "translate_hotkey": data.get("hotkey_translate")
            or hotkey.DEFAULT_TRANSLATE_HOTKEY,
            "snip_hotkey": data.get("hotkey_snip")
            or hotkey.DEFAULT_SNIP_HOTKEY,
        }

        try:
            hotkey.register_hotkeys(enable_snip=True, **wanted)
            self._last_good_hotkeys = wanted
            return True
        except Exception as exc:  # noqa: BLE001 - 组合键非法或钩子注册失败
            print(f"[hotkey] 注册快捷键失败：{exc}")

            if self._last_good_hotkeys:
                print(f"[hotkey] 已回滚到之前的快捷键：{self._last_good_hotkeys}")
                try:
                    hotkey.register_hotkeys(
                        enable_snip=True, **self._last_good_hotkeys
                    )
                except Exception as rollback_exc:  # noqa: BLE001
                    print(f"[hotkey] 回滚也失败了：{rollback_exc}")
            return False

    def setup_tray(self) -> bool:
        """创建托盘图标并接上菜单。

        Returns:
            bool: 是否创建成功（系统不支持托盘时返回 False）。
        """
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return False

        tray = TrayIcon(_load_icon(), self.window)
        tray.action_translate.triggered.connect(self.run_selection_translate)
        tray.action_snip.triggered.connect(self.on_snip_trigger)
        tray.action_settings.triggered.connect(self.open_settings)
        tray.action_quit.triggered.connect(self._app.quit)
        tray.double_clicked.connect(self.open_settings)
        tray.show()
        self.tray = tray
        return True

    # ---------- 设置 ----------

    def open_settings(self) -> None:
        """打开设置窗口，并填入当前保存的值。"""
        self.settings_window.load_from(load_user_settings())
        self.settings_window.open_settings()

    def test_connection(self, config) -> str:
        """设置界面里的「测试连接」：发一句问候语验证 Key 可用。"""
        probe = replace(config, timeout=min(config.timeout, TEST_TIMEOUT))
        return translate_api.translate("Hello, world!", probe)

    def _on_settings_saved(self, data: dict) -> None:
        """设置保存后：刷新配置并重新注册快捷键，立即生效。"""
        config = build_config(data)
        if config is not None:
            self.config = config

        hotkeys_ok = self.apply_hotkeys(data)

        if self.tray is not None:
            if hotkeys_ok:
                self.tray.notify(APP_TITLE, "设置已保存，快捷键已更新。")
            else:
                self.tray.notify(
                    APP_TITLE,
                    "设置已保存，但快捷键注册失败，请看终端提示。",
                )

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
        if self.config is None:
            return "还没有配置 API Key，请右键托盘图标 →「设置…」填写。"
        try:
            return translate_api.translate(text, self.config)
        except Exception as exc:  # noqa: BLE001
            return f"翻译失败：{exc}"


def main() -> int:
    """初始化配置与界面，注册快捷键并进入事件循环。"""
    if not _acquire_single_instance():
        print("[main] 已有一个实例在运行，请勿重复启动（重复启动会让快捷键触发多次）。")
        return 1

    app = ensure_app()
    app.setQuitOnLastWindowClosed(False)
    app.setWindowIcon(_load_icon())

    # 配置：用户设置优先，其次回退到 .env
    try:
        config = load_effective_config()
        configured = True
    except ValueError as exc:
        config = None
        configured = False
        print(f"[config] {exc}")

    translator_app = TranslatorApp(app, config)

    try:
        translator_app.start()
    except Exception as exc:  # noqa: BLE001
        print(f"[hotkey] 注册快捷键失败：{exc}")
        print("提示：若目标程序以管理员身份运行，请用管理员权限的终端启动本程序。")
        return 1

    if not translator_app.setup_tray():
        print("[warn] 系统托盘不可用，可以先把 API Key 填好再启动。")

    app.aboutToQuit.connect(translator_app.stop)

    if configured:
        masked = (
            f"{config.api_key[:7]}...{config.api_key[-4:]}"
            if len(config.api_key) > 11
            else "***"
        )
        print(f"[ready] 已就绪 | model={config.model} | key={masked}")
    else:
        print("[setup] 还没有配置 API Key，已为你打开设置窗口。")
        translator_app.open_settings()

    keys = hotkey.current_hotkeys()
    print(f"[ready] 划词翻译：{keys[hotkey.ACTION_TRANSLATE]}")
    print(f"[ready] 截图翻译：{keys[hotkey.ACTION_SNIP]}"
          "（拖出选区 -> 调整 -> 再按一次确认识别）")
    print("[ready] 双击托盘图标打开设置；右键菜单可改配置或退出。")

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
