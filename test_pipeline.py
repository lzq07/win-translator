"""最小链路自测：config -> translate -> ui。

用法：
    python test_pipeline.py                  # 用内置示例文本
    python test_pipeline.py "Hello, world!"  # 翻译指定文本

不涉及全局快捷键与 OCR。
"""

import sys

from PyQt6.QtWidgets import QApplication

from translator.config import load_config
from translator.translate import translate
from translator.ui import ResultWindow

DEFAULT_TEXT = "The quick brown fox jumps over the lazy dog."


def main() -> int:
    text = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_TEXT

    # 1) config：从 .env 读取 Key / URL
    try:
        cfg = load_config()
    except ValueError as exc:
        print(f"[config] 失败：{exc}")
        return 1

    masked = f"{cfg.api_key[:7]}...{cfg.api_key[-4:]}" if len(cfg.api_key) > 11 else "***"
    print(f"[config] base_url = {cfg.base_url}")
    print(f"[config] model    = {cfg.model}")
    print(f"[config] api_key  = {masked}")

    # 2) translate：调用 DeepSeek
    print(f"[translate] 原文: {text}")
    try:
        result = translate(text, cfg)
    except Exception as exc:  # noqa: BLE001 - 测试脚本需要暴露全部错误
        print(f"[translate] 失败：{exc}")
        return 1
    print(f"[translate] 译文: {result}")

    # 3) ui：弹出置顶窗口
    app = QApplication(sys.argv)
    window = ResultWindow()
    window.show_result(text, result)
    print("[ui] 弹窗已显示，按 Esc 或点「关闭」退出。")
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
