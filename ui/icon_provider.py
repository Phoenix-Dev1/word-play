from PyQt6.QtGui import QPainter, QColor, QLinearGradient, QPainterPath, QIcon, QPixmap, QPen
from PyQt6.QtCore import Qt, QRectF

class TrayIconProvider:
    @staticmethod
    def get_icon(state="default", size=64):
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # 1. Background Capsule
        rect = QRectF(size*0.05, size*0.05, size*0.9, size*0.9)
        grad = QLinearGradient(0, 0, 0, size)
        
        if state == "syncing":
            grad.setColorAt(0, QColor("#00d2ff")) # Cyan
            grad.setColorAt(1, QColor("#3a7bd5"))
        elif state == "paused":
            grad.setColorAt(0, QColor("#555555")) # Grey
            grad.setColorAt(1, QColor("#222222"))
        else:
            grad.setColorAt(0, QColor("#2c3e50")) # Deep Navy
            grad.setColorAt(1, QColor("#000000"))

        painter.setBrush(grad)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(rect, size*0.2, size*0.2)

        # 2. Stylized Musical Note Glyph
        note_path = QPainterPath()
        # Head
        note_path.addEllipse(QRectF(size*0.3, size*0.6, size*0.25, size*0.18))
        # Stem
        note_path.addRect(QRectF(size*0.5, size*0.25, size*0.05, size*0.42))
        # Flag
        note_path.moveTo(size*0.5, size*0.25)
        note_path.lineTo(size*0.75, size*0.35)
        note_path.lineTo(size*0.75, size*0.45)
        note_path.lineTo(size*0.5, size*0.35)
        note_path.closeSubpath()
        
        painter.setBrush(QColor("white"))
        painter.drawPath(note_path)

        # 3. State Overlays
        if state == "paused":
            painter.setBrush(QColor("#FFCC00"))
            painter.drawRoundedRect(QRectF(size*0.65, size*0.6, size*0.08, size*0.2), 2, 2)
            painter.drawRoundedRect(QRectF(size*0.78, size*0.6, size*0.08, size*0.2), 2, 2)
        
        if state == "syncing":
            pen = QPen(QColor(0, 210, 255, 150))
            pen.setWidth(max(1, int(size // 15)))
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(rect)

        painter.end()
        return QIcon(pixmap)
