"""界面模块：PyQt6 结果弹窗与截图框选遮罩。"""

from __future__ import annotations

import sys

from PyQt6.QtCore import QPoint, QRect, Qt, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QFont,
    QGuiApplication,
    QKeySequence,
    QPainter,
    QPen,
    QShortcut,
)
from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizeGrip,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

__all__ = ["ResultWindow", "SnipOverlay", "ensure_app", "virtual_desktop_rect"]


def virtual_desktop_rect() -> QRect:
    """返回覆盖所有显示器的虚拟桌面矩形（逻辑坐标，原点可能为负）。"""
    rect = QRect()
    for screen in QGuiApplication.screens():
        rect = rect.united(screen.geometry())
    return rect


WINDOW_STYLE = """
QWidget {
    background: #1f2430;
    color: #e6e6e6;
    font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif;
}
QLabel { color: #9aa4b2; font-size: 12px; }
QTextEdit {
    background: #171b24;
    border: 1px solid #2c3444;
    border-radius: 6px;
    padding: 8px;
    font-size: 15px;
    selection-background-color: #3d5afe;
}
QPushButton {
    background: #2c3444;
    border: none;
    border-radius: 6px;
    padding: 6px 16px;
    font-size: 13px;
}
QPushButton:hover { background: #3a465c; }
QPushButton:pressed { background: #232b3a; }
QSplitter::handle { background: #2c3444; height: 4px; }
QSplitter::handle:hover { background: #3d5afe; }
"""


def ensure_app() -> QApplication:
    """获取或创建 QApplication 实例（全局只能有一个）。"""
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


class ResultWindow(QWidget):
    """翻译结果弹窗：置顶、可自由缩放，原文/译文之间的分隔线可拖动。"""

    MIN_WIDTH = 360
    MIN_HEIGHT = 240

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._original = QTextEdit()
        self._translated = QTextEdit()
        self._splitter = QSplitter()
        self._build_ui()

    def _build_ui(self):
        self.setWindowTitle("翻译结果")
        self.resize(560, 420)
        self.setMinimumSize(self.MIN_WIDTH, self.MIN_HEIGHT)
        # 置顶 + 不在任务栏显示图标（保留原生边框，可拖动边角缩放）
        self.setWindowFlags(
            Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool
        )
        self.setStyleSheet(WINDOW_STYLE)

        self._original.setReadOnly(True)
        self._original.setPlaceholderText("原文")

        self._translated.setReadOnly(True)
        self._translated.setPlaceholderText("译文")
        font = QFont()
        font.setPointSize(11)
        self._translated.setFont(font)

        # 原文 / 译文 上下分区，中间分隔线可拖动调整比例
        self._splitter.setOrientation(Qt.Orientation.Vertical)
        self._splitter.setChildrenCollapsible(False)
        self._splitter.addWidget(self._section("原文", self._original))
        self._splitter.addWidget(self._section("译文", self._translated))
        self._splitter.setSizes([120, 280])

        btn_copy = QPushButton("复制译文")
        btn_copy.clicked.connect(self._copy_translated)

        btn_close = QPushButton("关闭 (Esc)")
        btn_close.clicked.connect(self.close)

        btn_row = QHBoxLayout()
        btn_row.addWidget(QSizeGrip(self))  # 右下角缩放手柄
        btn_row.addStretch(1)
        btn_row.addWidget(btn_copy)
        btn_row.addWidget(btn_close)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 12)
        layout.setSpacing(8)
        layout.addWidget(self._splitter, 1)
        layout.addLayout(btn_row)

        QShortcut(QKeySequence("Esc"), self, activated=self.close)

    @staticmethod
    def _section(title: str, editor: QTextEdit) -> QWidget:
        """给编辑框套上标题，作为分割面板的一节。"""
        box = QWidget()
        box_layout = QVBoxLayout(box)
        box_layout.setContentsMargins(0, 0, 0, 0)
        box_layout.setSpacing(4)
        box_layout.addWidget(QLabel(title))
        box_layout.addWidget(editor, 1)
        return box

    def show_result(self, original: str = "", translated: str = "") -> None:
        """显示原文与译文并置顶弹出。

        Args:
            original: 原文。
            translated: 译文。
        """
        self._original.setPlainText(original or "")
        self._translated.setPlainText(translated or "")
        self.show()
        self.raise_()
        self.activateWindow()

    def _copy_translated(self) -> None:
        """把译文复制到剪贴板。"""
        text = self._translated.toPlainText()
        if text:
            QApplication.clipboard().setText(text)


class SnipOverlay(QWidget):
    """全屏框选遮罩。

    交互：
        - 空白处按住左键拖拽 -> 建立新选区
        - 拖动选区内部 -> 整体移动
        - 拖动 8 个手柄 -> 调整大小
        - Esc / 右键 -> 取消
        - Enter / 外部调用 confirm() -> 确认（默认行为见 confirm_on_release）

    信号：
        confirmed(QRect): 确认框选，参数为**全局屏幕坐标**的矩形。
        canceled(): 取消（Esc / 右键）。
    """

    # 选区最小边长（像素）
    MIN_SIZE = 8
    # 手柄绘制尺寸 / 命中容差
    HANDLE_SIZE = 8
    HANDLE_HIT = 7

    confirmed = pyqtSignal(QRect)
    canceled = pyqtSignal()

    _CURSORS = {
        "tl": Qt.CursorShape.SizeFDiagCursor,
        "br": Qt.CursorShape.SizeFDiagCursor,
        "tr": Qt.CursorShape.SizeBDiagCursor,
        "bl": Qt.CursorShape.SizeBDiagCursor,
        "l": Qt.CursorShape.SizeHorCursor,
        "r": Qt.CursorShape.SizeHorCursor,
        "t": Qt.CursorShape.SizeVerCursor,
        "b": Qt.CursorShape.SizeVerCursor,
    }

    def __init__(self, confirm_on_release: bool = False):
        """
        Args:
            confirm_on_release: 拖出选区松手后是否立即确认。
                False（默认）时松手只建立选区，等待再次确认，方便二次调整。
        """
        super().__init__()
        self._confirm_on_release = confirm_on_release
        self._origin = QPoint()
        self._rect = QRect()
        self._drag_mode = ""  # "" | "new" | "move" | "resize"
        self._handle = ""
        self._press_pos = QPoint()
        self._rect_at_press = QRect()

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        vrect = virtual_desktop_rect()
        self._origin = vrect.topLeft()
        self.setGeometry(vrect)

    # ---------- 对外接口 ----------

    def start(self) -> None:
        """显示遮罩并开始框选。"""
        self._rect = QRect()
        self._drag_mode = ""
        self._handle = ""
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus()
        self.update()

    @property
    def selection_rect(self) -> QRect:
        """当前选区（全局屏幕坐标）；无有效选区时返回空矩形。"""
        if self._rect.width() < self.MIN_SIZE or self._rect.height() < self.MIN_SIZE:
            return QRect()
        return self._rect.translated(self._origin)

    def confirm(self) -> bool:
        """确认当前选区。

        Returns:
            bool: 是否确认成功（选区过小时返回 False，遮罩保持不动）。
        """
        rect = self.selection_rect
        if rect.isEmpty():
            return False
        self.confirmed.emit(rect)
        return True

    # ---------- 绘制 ----------

    def paintEvent(self, event):  # noqa: N802 - Qt 约定的命名
        painter = QPainter(self)
        # 全屏压暗
        painter.fillRect(self.rect(), QColor(0, 0, 0, 110))

        rect = self._rect
        if rect.width() < 1 or rect.height() < 1:
            painter.end()
            return

        # 挖空选区，露出下方真实屏幕
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        painter.fillRect(rect, Qt.GlobalColor.transparent)
        painter.setCompositionMode(
            QPainter.CompositionMode.CompositionMode_SourceOver
        )

        painter.setPen(QPen(QColor("#3d5afe"), 2))
        painter.drawRect(rect)

        # 8 个手柄
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#3d5afe"))
        half = self.HANDLE_SIZE // 2
        for point in self._handle_points(rect):
            painter.drawRect(
                QRect(
                    point.x() - half,
                    point.y() - half,
                    self.HANDLE_SIZE,
                    self.HANDLE_SIZE,
                )
            )
        painter.setBrush(Qt.BrushStyle.NoBrush)

        # 尺寸提示
        label = f"{rect.width()} × {rect.height()}"
        painter.setPen(QColor("#ffffff"))
        text_rect = QRect(rect.left(), max(0, rect.top() - 24), 140, 18)
        painter.drawText(
            text_rect,
            int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter),
            label,
        )
        painter.end()

    # ---------- 内部工具 ----------

    @staticmethod
    def _handle_points(rect: QRect) -> list[QPoint]:
        """返回 8 个手柄的中心点（局部坐标）。"""
        cx = rect.center().x()
        cy = rect.center().y()
        return [
            QPoint(rect.left(), rect.top()),
            QPoint(cx, rect.top()),
            QPoint(rect.right(), rect.top()),
            QPoint(rect.left(), cy),
            QPoint(rect.right(), cy),
            QPoint(rect.left(), rect.bottom()),
            QPoint(cx, rect.bottom()),
            QPoint(rect.right(), rect.bottom()),
        ]

    def _handle_at(self, pos: QPoint) -> str:
        """判断鼠标落在哪个手柄上，没有则返回空串。"""
        rect = self._rect
        if rect.width() < self.MIN_SIZE or rect.height() < self.MIN_SIZE:
            return ""

        tol = self.HANDLE_HIT
        on_left = abs(pos.x() - rect.left()) <= tol
        on_right = abs(pos.x() - rect.right()) <= tol
        on_top = abs(pos.y() - rect.top()) <= tol
        on_bottom = abs(pos.y() - rect.bottom()) <= tol
        within_x = rect.left() - tol <= pos.x() <= rect.right() + tol
        within_y = rect.top() - tol <= pos.y() <= rect.bottom() + tol

        if on_left and on_top:
            return "tl"
        if on_right and on_top:
            return "tr"
        if on_left and on_bottom:
            return "bl"
        if on_right and on_bottom:
            return "br"
        if on_left and within_y:
            return "l"
        if on_right and within_y:
            return "r"
        if on_top and within_x:
            return "t"
        if on_bottom and within_x:
            return "b"
        return ""

    def _resized_rect(self, handle: str, pos: QPoint) -> QRect:
        """根据被拖动的边/角计算新选区。"""
        rect = QRect(self._rect_at_press)
        if "l" in handle:
            rect.setLeft(min(pos.x(), rect.right() - self.MIN_SIZE))
        if "r" in handle:
            rect.setRight(max(pos.x(), rect.left() + self.MIN_SIZE))
        if "t" in handle:
            rect.setTop(min(pos.y(), rect.bottom() - self.MIN_SIZE))
        if "b" in handle:
            rect.setBottom(max(pos.y(), rect.top() + self.MIN_SIZE))
        return self._clamp(rect)

    def _clamp(self, rect: QRect) -> QRect:
        """把选区限制在遮罩范围内。"""
        bounds = self.rect()
        rect = QRect(rect)
        if rect.left() < bounds.left():
            rect.moveLeft(bounds.left())
        if rect.top() < bounds.top():
            rect.moveTop(bounds.top())
        if rect.right() > bounds.right():
            rect.moveRight(bounds.right())
        if rect.bottom() > bounds.bottom():
            rect.moveBottom(bounds.bottom())
        return rect

    def _update_cursor(self, pos: QPoint) -> None:
        handle = self._handle_at(pos)
        if handle:
            self.setCursor(self._CURSORS[handle])
        elif self._rect.contains(pos):
            self.setCursor(Qt.CursorShape.SizeAllCursor)
        else:
            self.setCursor(Qt.CursorShape.CrossCursor)

    # ---------- 事件 ----------

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.MouseButton.RightButton:
            self.canceled.emit()
            return
        if event.button() != Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            return

        pos = event.position().toPoint()
        self._press_pos = pos
        self._rect_at_press = QRect(self._rect)

        handle = self._handle_at(pos)
        if handle:
            self._drag_mode = "resize"
            self._handle = handle
        elif self._rect.contains(pos):
            self._drag_mode = "move"
            self._handle = ""
        else:
            self._drag_mode = "new"
            self._handle = ""
            self._rect = QRect(pos, pos)
        self.update()

    def mouseMoveEvent(self, event):  # noqa: N802
        pos = event.position().toPoint()

        if self._drag_mode == "new":
            self._rect = QRect(self._press_pos, pos).normalized()
        elif self._drag_mode == "move":
            self._rect = self._clamp(
                self._rect_at_press.translated(pos - self._press_pos)
            )
        elif self._drag_mode == "resize":
            self._rect = self._resized_rect(self._handle, pos)
        else:
            self._update_cursor(pos)
            return

        self._update_cursor(pos)
        self.update()

    def mouseReleaseEvent(self, event):  # noqa: N802
        if event.button() != Qt.MouseButton.LeftButton or not self._drag_mode:
            return

        if self._drag_mode == "new":
            rect = QRect(self._press_pos, event.position().toPoint()).normalized()
            if rect.width() >= self.MIN_SIZE and rect.height() >= self.MIN_SIZE:
                self._rect = rect
                self._drag_mode = ""
                self._update_cursor(event.position().toPoint())
                self.update()
                if self._confirm_on_release:
                    self.confirmed.emit(self.selection_rect)
                return
            # 只是点了一下，不算选区
            self._rect = QRect()

        self._drag_mode = ""
        self._handle = ""
        self.update()

    def keyPressEvent(self, event):  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self.canceled.emit()
        elif event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.confirm()
        else:
            super().keyPressEvent(event)
