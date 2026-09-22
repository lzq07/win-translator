"""OCR 模块：截图框选 + Windows 内置 OCR (Windows.Media.Ocr) 识别文字。

依赖系统的 OCR 语言包。已验证本机支持 zh-Hans-CN 与 en-US。
"""

from __future__ import annotations

import asyncio
import re
import time

from PyQt6.QtCore import QBuffer, QEventLoop, QIODevice, QRect, Qt
from PyQt6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPixmap
from winrt.windows.globalization import Language
from winrt.windows.graphics.imaging import BitmapDecoder
from winrt.windows.media.ocr import OcrEngine
from winrt.windows.storage.streams import DataWriter, InMemoryRandomAccessStream

from .ui import SnipOverlay

# 默认识别语言
DEFAULT_OCR_LANGUAGE = "zh-Hans-CN"

# Windows OCR 会在 CJK 字符之间插入多余空格（"你 好 世 界"），需要去掉
_CJK = r"\u4e00-\u9fff\u3400-\u4dbf\u3040-\u30ff\uf900-\ufaff"
_CJK_SPACE_RE = re.compile(rf"(?<=[{_CJK}])[ \u3000]+(?=[{_CJK}])")

# 平均亮度低于该值视为深色背景，需要反色后再识别
DARK_MEAN_LIGHTNESS = 110
# 图片高度小于该值时放大，提高小字识别率
MIN_OCR_HEIGHT = 40

__all__ = [
    "DEFAULT_OCR_LANGUAGE",
    "capture_screen_region",
    "grab_region",
    "ocr_image",
    "ocr_from_clipboard",
    "tidy_text",
]


def tidy_text(text: str) -> str:
    """清理 OCR 结果：去掉 CJK 字符之间被插入的多余空格。

    Args:
        text: OCR 原始文本。

    Returns:
        str: 清理后的文本。
    """
    if not text:
        return ""
    return _CJK_SPACE_RE.sub("", text).strip()


def grab_region(rect: QRect) -> QImage:
    """实时抓取屏幕上的指定区域（全局坐标），支持跨显示器拼接。

    Args:
        rect: 全局坐标下的矩形。

    Returns:
        QImage: 该区域的图像，尺寸等于 rect.size()。
    """
    canvas = QImage(rect.size(), QImage.Format.Format_RGB32)
    canvas.fill(Qt.GlobalColor.black)

    painter = QPainter(canvas)
    for screen in QGuiApplication.screens():
        inter = rect.intersected(screen.geometry())
        if inter.isEmpty():
            continue
        # 转成该屏幕内的局部坐标
        local = inter.translated(-screen.geometry().topLeft())
        shot = screen.grabWindow(
            0, local.x(), local.y(), local.width(), local.height()
        )
        painter.drawImage(inter.topLeft() - rect.topLeft(), shot.toImage())
    painter.end()
    return canvas


def capture_screen_region(confirm_on_release: bool = True) -> QImage | None:
    """弹出全屏遮罩，框选完成后**实时**抓取该区域（阻塞式，供测试脚本使用）。

    抓取动作放在「框选结束 + 遮罩隐藏」之后，而不是弹遮罩之前，
    这样 Alt+Tab 切到别的窗口再框选，拿到的是切换后的画面，而不是弹遮罩瞬间的旧画面。

    Args:
        confirm_on_release: 拖出选区松手后是否立即确认。True 为一次拖拽完成；
            False 时松手只建立选区，需要再次按键（由调用方调用 confirm()）才确认。

    Returns:
        QImage: 选中区域的图像；用户取消（Esc / 右键 / 选区过小）时返回 None。
    """
    overlay = SnipOverlay(confirm_on_release=confirm_on_release)
    result: dict = {}
    loop = QEventLoop()

    def on_confirmed(rect: QRect) -> None:
        result["rect"] = rect
        loop.quit()

    def on_canceled() -> None:
        loop.quit()

    overlay.confirmed.connect(on_confirmed)
    overlay.canceled.connect(on_canceled)
    overlay.start()
    loop.exec()

    overlay.hide()
    overlay.deleteLater()

    rect = result.get("rect")
    if rect is None:
        return None

    # 等画面刷新一帧，确保抓到的画面里不含遮罩
    QGuiApplication.processEvents()
    time.sleep(0.06)
    QGuiApplication.processEvents()

    return grab_region(rect)


def _as_qimage(image) -> QImage:
    """把 QImage / QPixmap 统一转成 QImage。"""
    if isinstance(image, QPixmap):
        image = image.toImage()
    if not isinstance(image, QImage):
        raise TypeError(f"不支持的图像类型：{type(image)!r}")
    return image


def _preprocess_for_ocr(image: QImage) -> QImage:
    """识别前的预处理，提升 Windows OCR 的成功率。

    1. 深色背景（平均亮度低于 DARK_MEAN_LIGHTNESS）自动反色成黑字白底。
       Windows OCR 针对浅底黑字训练，直接喂暗色主题截图会一个字都识别不出。
    2. 高度不足 MIN_OCR_HEIGHT 的小图放大，提高小字号识别率。

    Args:
        image: 原始截图。

    Returns:
        QImage: 处理后的图像；无法处理时原样返回。
    """
    if image.isNull() or image.width() == 0 or image.height() == 0:
        return image

    img = image.convertToFormat(QImage.Format.Format_RGB32)
    width, height = img.width(), img.height()

    # 稀疏采样估算平均亮度
    step = max(1, min(width, height) // 40)
    total = 0
    count = 0
    for y in range(0, height, step):
        for x in range(0, width, step):
            total += QColor.fromRgba(img.pixel(x, y)).lightness()
            count += 1
    mean_lightness = total / count if count else 255

    if mean_lightness < DARK_MEAN_LIGHTNESS:
        img.invertPixels(QImage.InvertMode.InvertRgb)

    if height < MIN_OCR_HEIGHT:
        scale = max(2, round(MIN_OCR_HEIGHT / height))
        img = img.scaled(
            width * scale,
            height * scale,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

    return img


def _to_png_bytes(image) -> bytes:
    """把 QImage / QPixmap（或已是 PNG 的字节）转成 PNG 字节。"""
    if isinstance(image, (bytes, bytearray)):
        return bytes(image)

    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    _as_qimage(image).save(buffer, "PNG")
    buffer.close()
    return bytes(buffer.data())


async def _recognize_async(png_bytes: bytes, language: str) -> str:
    """把 PNG 字节送入 Windows.Media.Ocr，返回识别文本。"""
    stream = InMemoryRandomAccessStream()
    writer = DataWriter(stream)
    writer.write_bytes(png_bytes)
    await writer.store_async()
    await writer.flush_async()
    stream.seek(0)

    decoder = await BitmapDecoder.create_async(stream)
    bitmap = await decoder.get_software_bitmap_async()

    engine = OcrEngine.try_create_from_language(Language(language))
    if engine is None:
        engine = OcrEngine.try_create_from_user_profile_languages()
    if engine is None:
        raise RuntimeError(
            "系统没有可用的 OCR 语言，请在 Windows「设置 → 时间和语言」中安装语言包。"
        )

    result = await engine.recognize_async(bitmap)
    return result.text


def ocr_image(image, language: str = DEFAULT_OCR_LANGUAGE) -> str:
    """对图片做 OCR 识别。

    Args:
        image: QImage / QPixmap / PNG 字节。
        language: 识别语言标签，默认 zh-Hans-CN。

    Returns:
        str: 识别出的文本（已清理 CJK 多余空格）。

    Raises:
        RuntimeError: 系统无可用 OCR 语言或识别失败。
    """
    if isinstance(image, (bytes, bytearray)):
        png = bytes(image)  # 已是编码好的图片，跳过预处理
    else:
        png = _to_png_bytes(_preprocess_for_ocr(_as_qimage(image)))

    return tidy_text(asyncio.run(_recognize_async(png, language)))


def ocr_from_clipboard(language: str = DEFAULT_OCR_LANGUAGE) -> str:
    """识别剪贴板中的图片。

    Returns:
        str: 识别出的文本；剪贴板无图片则返回空字符串。
    """
    image = QGuiApplication.clipboard().image()
    if image.isNull():
        return ""
    return ocr_image(image, language)
