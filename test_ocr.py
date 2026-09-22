"""截图 OCR 自测：框选屏幕区域 -> Windows OCR 识别 -> 终端打印文字。

用法：
    python test_ocr.py

操作：
    拖拽左键框选一段中文区域，松开即识别；Esc 或右键取消。
    截图会另存为 snip_test.png，方便对比识别效果。
"""

import sys

from PyQt6.QtWidgets import QApplication

from translator.ocr import capture_screen_region, ocr_image

OUTPUT_PNG = "snip_test.png"


def main() -> int:
    app = QApplication(sys.argv)  # noqa: F841 - OCR 需要 GUI 应用实例

    print("请拖拽框选一段中文区域（Esc / 右键取消）…")
    image = capture_screen_region()

    if image is None:
        print("已取消，未框选。")
        return 1

    print(f"[capture] 截图尺寸 = {image.width()} x {image.height()}")
    image.save(OUTPUT_PNG)
    print(f"[capture] 已保存 {OUTPUT_PNG}")

    print("[ocr] 识别中…")
    try:
        text = ocr_image(image)
    except Exception as exc:  # noqa: BLE001 - 测试脚本需要暴露全部错误
        print(f"[ocr] 失败：{exc}")
        return 1

    if not text:
        print("[ocr] 未识别到任何文字。")
        return 1

    print("[ocr] 识别结果：")
    print("-" * 40)
    print(text)
    print("-" * 40)
    return 0


if __name__ == "__main__":
    sys.exit(main())
