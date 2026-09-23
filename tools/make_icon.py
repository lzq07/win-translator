"""生成应用图标 assets/icon.ico（多尺寸）与 assets/icon.png。

用法：
    python tools/make_icon.py

不依赖 Pillow：直接按 ICO 容器格式写出（Vista 起支持内嵌 PNG）。
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

from PyQt6.QtCore import QBuffer, QIODevice, QRectF, Qt
from PyQt6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QGuiApplication,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
)

# 需要打包进 ico 的尺寸
SIZES = (16, 24, 32, 48, 64, 128, 256)
ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
GLYPH = "译"


def render(size: int) -> QImage:
    """绘制指定边长的图标位图。"""
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)

    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

    # 圆角渐变底
    radius = size * 0.22
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, size, size), radius, radius)

    gradient = QLinearGradient(0, 0, size, size)
    gradient.setColorAt(0.0, QColor("#4f6bff"))
    gradient.setColorAt(1.0, QColor("#1b2a6b"))
    painter.fillPath(path, QBrush(gradient))

    # 居中的字形
    font = QFont("Microsoft YaHei")
    font.setBold(True)
    font.setPixelSize(max(8, int(size * 0.66)))
    painter.setFont(font)
    painter.setPen(QColor("#ffffff"))
    painter.drawText(
        QRectF(0, 0, size, size),
        int(Qt.AlignmentFlag.AlignCenter),
        GLYPH,
    )

    painter.end()
    return image


def png_bytes(image: QImage) -> bytes:
    """把 QImage 编码成 PNG 字节。"""
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    buffer.close()
    return bytes(buffer.data())


def build_ico(pngs: dict[int, bytes]) -> bytes:
    """按 ICO 容器格式拼装多尺寸图标（每帧直接内嵌 PNG 数据）。

    Args:
        pngs: {边长: PNG 字节}。

    Returns:
        bytes: 完整的 .ico 文件内容。
    """
    count = len(pngs)
    header = struct.pack("<HHH", 0, 1, count)  # reserved, type=icon, count

    entries = b""
    payload = b""
    offset = 6 + 16 * count
    for size in sorted(pngs):
        data = pngs[size]
        # 256 用 0 表示
        dimension = 0 if size >= 256 else size
        entries += struct.pack(
            "<BBBBHHII",
            dimension,
            dimension,
            0,  # 调色板数
            0,  # reserved
            1,  # 色彩平面
            32,  # 位深
            len(data),
            offset,
        )
        offset += len(data)
        payload += data

    return header + entries + payload


def main() -> int:
    app = QGuiApplication(sys.argv)  # noqa: F841 - QPainter 需要 GUI 应用实例
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)

    pngs = {size: png_bytes(render(size)) for size in SIZES}

    ico_path = ASSETS_DIR / "icon.ico"
    ico_path.write_bytes(build_ico(pngs))

    png_path = ASSETS_DIR / "icon.png"
    render(256).save(str(png_path), "PNG")

    print(f"已生成 {ico_path}（{len(pngs)} 个尺寸，{ico_path.stat().st_size} 字节）")
    print(f"已生成 {png_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
