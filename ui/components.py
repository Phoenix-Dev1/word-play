from PyQt6.QtWidgets import QScrollArea
from PyQt6.QtCore import QPropertyAnimation, QEasingCurve, QAbstractAnimation

class SmoothScrollArea(QScrollArea):
    """A custom QScrollArea that provides smooth, easing-based kinetic scrolling."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.target_value = 0
        self.animation = QPropertyAnimation(self.verticalScrollBar(), b"value")
        self.animation.setDuration(250)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if delta == 0:
            return
            
        scroll_step = 120 # pixels per tick
        
        # Determine the base value to start from
        if self.animation.state() == QAbstractAnimation.State.Running:
            current_base = self.target_value
        else:
            current_base = self.verticalScrollBar().value()
            
        self.target_value = int(current_base - (delta / 120.0 * scroll_step))
        
        # Clamp target
        self.target_value = max(0, min(self.target_value, self.verticalScrollBar().maximum()))
        
        # Animate to target
        self.animation.stop()
        self.animation.setStartValue(self.verticalScrollBar().value())
        self.animation.setEndValue(self.target_value)
        self.animation.start()
        
        event.accept()
