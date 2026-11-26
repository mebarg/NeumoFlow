"""Phase markers shared by the screen and printed z-score charts."""
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPen


def draw_zscore_marker(painter, x, y, radius, phase):
    painter.save()
    color = QColor('#2563eb' if phase == 'pre' else '#dc2626')
    if phase == 'pre':
        painter.setPen(Qt.NoPen)
        painter.setBrush(color)
    else:
        # A larger open ring also remains visible when PRE and POST coincide.
        radius *= 1.4
        painter.setPen(QPen(color, radius * .32))
        painter.setBrush(Qt.NoBrush)
    painter.drawEllipse(QPointF(x, y), radius, radius)
    painter.restore()
