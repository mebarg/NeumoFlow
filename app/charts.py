import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget


CURVE_COLORS = [
    "#2563eb",
    "#dc2626",
    "#ca8a04",
    "#7c3aed",
    "#0f766e",
    "#ea580c",
    "#0891b2",
    "#be123c",
    "#4d7c0f",
    "#9333ea",
    "#1d4ed8",
    "#c026d3",
    "#0369a1",
    "#b45309",
    "#15803d",
    "#db2777",
    "#4338ca",
    "#65a30d",
    "#b91c1c",
    "#0e7490",
]


class CurveWidget(QWidget):
    def __init__(self, mode, parent=None):
        super().__init__(parent)
        self.mode = mode
        self.curves = []
        self.curve_colors = []
        self.highlighted_curve = None
        self.print_mode = False
        self.calibration_mode = False
        self._study_limits = None
        self._volume_step = 1.
        self.setMinimumHeight(180)

    def set_curve(self, vol_curve):
        self.set_curves([vol_curve] if vol_curve else [])

    def set_curves(self, curves):
        self.curves = [list(curve or []) for curve in curves if curve]
        self._expand_study_axes()
        self.update()

    def set_curve_styles(self, colors, highlighted=None):
        """Presentation only: keep a maneuver's color when other curves are hidden."""
        self.curve_colors = list(colors)
        self.highlighted_curve = highlighted
        self.update()

    def configure_study_axes(self, volume_l, time_s=10., flow_lps=12.):
        """Reserve both signs before capture; grow only when data exceed bounds."""
        if not all(math.isfinite(v) and v>0 for v in (volume_l,time_s,flow_lps)):
            raise ValueError('Escalas de gráfico inválidas')
        volume=volume_l*1.1
        self._volume_step=max(1.,volume/4)
        self._time_step=time_s
        self._study_limits={'time':time_s,'volume_min':-volume,'volume_max':volume,'flow':flow_lps}
        self._expand_study_axes()
        self.update()

    def _expand_study_axes(self):
        if self._study_limits is None or self.calibration_mode:
            return
        limits=self._study_limits
        for curve in self.curves:
            for t,v,f in curve:
                if not all(math.isfinite(x) for x in (t,v,f)):
                    continue
                if t>limits['time']:
                    limits['time']=math.ceil(t/self._time_step)*self._time_step
                if v>limits['volume_max']:
                    limits['volume_max']+=math.ceil((v-limits['volume_max'])/self._volume_step)*self._volume_step
                if v<limits['volume_min']:
                    limits['volume_min']-=math.ceil((limits['volume_min']-v)/self._volume_step)*self._volume_step
                if abs(f)>limits['flow']:
                    limits['flow']=math.ceil(abs(f)/2)*2

    def study_axis_limits(self):
        if self._study_limits is None:
            return None
        limits=self._study_limits
        if self.mode=='flow_volume':
            return (limits['volume_min'],limits['volume_max'],-limits['flow'],limits['flow'])
        return (0.,limits['time'],limits['volume_min'],limits['volume_max'])

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor("#ffffff"))

        bounds = self.rect().adjusted(54, 18, -18, -38)
        border_color = "#000000" if self.print_mode else "#94a3b8"
        axis_color = "#000000" if self.print_mode else "#334155"
        grid_color = "#9ca3af" if self.print_mode else "#e2e8f0"
        painter.setPen(QPen(QColor(border_color), 1.4 if self.print_mode else 1))
        painter.drawRect(bounds)

        stable = self._study_limits is not None and not self.calibration_mode
        if not self.curves and not self.calibration_mode and not stable:
            painter.setPen(QColor("#64748b"))
            painter.drawText(self.rect(), Qt.AlignCenter, "Sin datos")
            return

        points = [point for curve in self.curves for point in curve]
        times = [t for t, _, _ in points]
        vols = [v for _, v, _ in points]
        flows = [f for _, _, f in points]

        if self.calibration_mode:
            xs = times or [0.0, 12.0]
            ys = vols or [-3.0, 3.0]
            x_label = "Tiempo (s)"
            y_label = "Volumen (L)"
            data_min_x = 0.0
            data_max_x = 12.0
            min_y = -3.3
            max_y = 3.3
        elif stable:
            data_min_x,data_max_x,min_y,max_y = self.study_axis_limits()
            x_label = "Volumen (L)" if self.mode=='flow_volume' else "Tiempo (s)"
            y_label = "Flujo (L/s)" if self.mode=='flow_volume' else "Volumen (L)"
        elif self.mode == "flow_volume":
            xs = vols
            ys = flows
            x_label = "Volumen (L)"
            y_label = "Flujo (L/s)"
            min_y = min(0.0, min(ys))
            max_y = max(ys)
        else:
            xs = times
            ys = vols
            x_label = "Tiempo (s)"
            y_label = "Volumen (L)"
            min_y = min(0.0, min(ys))
            max_y = max(ys)

        if not self.calibration_mode and not stable:
            data_min_x = min(0.0, min(xs))
            data_max_x = max(xs) or 1.0
        data_max_y = max_y or 1.0
        data_span_y = data_max_y - min_y or 1.0
        data_span_x = data_max_x - data_min_x or 1.0
        pad_x = 0.0 if self.calibration_mode or stable else data_span_x * 0.06
        pad_y = 0.0 if stable else data_span_y * 0.08
        min_x = data_min_x - pad_x
        max_x = data_max_x + pad_x
        min_y -= pad_y
        max_y = data_max_y + pad_y
        span_x = max_x - min_x or 1.0
        span_y = max_y - min_y or 1.0

        def map_point(x, y):
            px = bounds.left() + ((x - min_x) / span_x) * bounds.width()
            py = bounds.bottom() - ((y - min_y) / span_y) * bounds.height()
            return QPointF(px, py)

        painter.setPen(QPen(QColor(grid_color), 1))
        zero_y = map_point(0, 0).y()
        painter.drawLine(bounds.left(), zero_y, bounds.right(), zero_y)
        zero_x = map_point(0, 0).x()
        painter.drawLine(zero_x, bounds.top(), zero_x, bounds.bottom())
        if self.calibration_mode:
            painter.setPen(QPen(QColor("#ef4444"), 1, Qt.DashLine))
            for target_s in (1, 3, 6, 10):
                for target_v in (-3, 3):
                    painter.drawLine(map_point(0, 0), map_point(target_s, target_v))
            painter.setPen(QPen(QColor(grid_color), 1))
        if self.mode == "volume_time" or self.calibration_mode:
            first_second = max(0, math.ceil(min_x))
            last_second = math.floor(max_x)
            tick_step = max(1,math.ceil(span_x/10)) if stable else 1
            for second in range(first_second, last_second + 1, tick_step):
                x = map_point(second, 0).x()
                if second != 0:
                    painter.drawLine(x, bounds.top(), x, bounds.bottom())
                painter.setPen(QColor(axis_color))
                painter.drawText(QRectF(x - 14, bounds.bottom() + 4, 28, 16), Qt.AlignCenter, str(second))
                painter.setPen(QPen(QColor(grid_color), 1))

        if stable:
            # Fixed-grid ticks, including negative inspiration, before any data.
            def nice_step(span):
                raw=span/6
                power=10**math.floor(math.log10(raw))
                return next(n*power for n in (1,2,5,10) if n*power>=raw)
            y_step=nice_step(span_y)
            for i in range(math.ceil(min_y/y_step),math.floor(max_y/y_step)+1):
                value=i*y_step
                py=map_point(0,value).y()
                painter.setPen(QPen(QColor(grid_color),1))
                painter.drawLine(bounds.left(),py,bounds.right(),py)
                painter.setPen(QColor(axis_color))
                painter.drawText(QRectF(20,py-8,30,16),Qt.AlignRight | Qt.AlignVCenter,f'{value:g}')
            if self.mode=='flow_volume':
                x_step=nice_step(span_x)
                for i in range(math.ceil(min_x/x_step),math.floor(max_x/x_step)+1):
                    value=i*x_step
                    px=map_point(value,0).x()
                    painter.setPen(QPen(QColor(grid_color),1))
                    painter.drawLine(px,bounds.top(),px,bounds.bottom())
                    painter.setPen(QColor(axis_color))
                    painter.drawText(QRectF(px-18,bounds.bottom()+4,36,16),Qt.AlignCenter,f'{value:g}')

        for idx, curve in enumerate(self.curves):
            if self.mode == "flow_volume":
                curve_xs = [v for _, v, _ in curve]
                curve_ys = [f for _, _, f in curve]
            else:
                curve_xs = [t for t, _, _ in curve]
                curve_ys = [v for _, v, _ in curve]
            path = QPainterPath()
            first = map_point(curve_xs[0], curve_ys[0])
            path.moveTo(first)
            for x, y in zip(curve_xs[1:], curve_ys[1:]):
                path.lineTo(map_point(x, y))
            emphasized = idx == (self.highlighted_curve if self.highlighted_curve is not None else len(self.curves) - 1)
            color = QColor(self.curve_colors[idx] if idx < len(self.curve_colors) else CURVE_COLORS[idx % len(CURVE_COLORS)])
            painter.setPen(QPen(color, 2.5 if emphasized else 1.6))
            painter.drawPath(path)

        painter.setPen(QColor(axis_color))
        if self.mode != "volume_time" and not stable:
            painter.drawText(bounds.left(), self.height() - 12, f"{data_min_x:.2f}" if data_min_x < 0 else "0")
            painter.drawText(bounds.right() - 36, self.height() - 12, f"{data_max_x:.2f}")
        painter.drawText(8, bounds.top() + 4, f"{data_max_y:.2f}")
        painter.drawText(QRectF(bounds.left(), self.height() - 18, bounds.width(), 18), Qt.AlignCenter, x_label)

        painter.save()
        painter.translate(16, bounds.center().y())
        painter.rotate(-90)
        fm = QFontMetrics(painter.font())
        painter.drawText(QRectF(-bounds.height() / 2, -10, bounds.height(), fm.height()), Qt.AlignCenter, y_label)
        painter.restore()


class ZScoreWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows = []
        self.threshold_label = "LLN"
        self.setMinimumHeight(130)
        self.setMaximumHeight(170)

    def set_rows(self, rows):
        self.rows = list(rows or [])
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor("#ffffff"))

        title_rect = QRectF(8, 4, self.width() - 16, 22)
        font = QFont(painter.font())
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor("#111827"))
        painter.drawText(title_rect, Qt.AlignLeft | Qt.AlignVCenter, "Z-score")

        if not self.rows:
            font.setBold(False)
            painter.setFont(font)
            painter.setPen(QColor("#64748b"))
            painter.drawText(self.rect(), Qt.AlignCenter, "Sin datos")
            return

        label_w = 86
        left = label_w + 10
        right = self.width() - 18
        top = 42
        bottom = self.height() - 30
        chart_w = max(1, right - left)
        row_h = max(18, (bottom - top) / len(self.rows))
        axis_min = -5.0
        axis_max = 2.0

        def map_x(value):
            bounded = max(axis_min, min(axis_max, value))
            return left + ((bounded - axis_min) / (axis_max - axis_min)) * chart_w

        normal_x = map_x(-1.645)
        painter.fillRect(QRectF(normal_x, top, right - normal_x, row_h * len(self.rows)), QColor("#dcfce7"))

        font.setBold(False)
        painter.setFont(font)
        painter.setPen(QPen(QColor("#d1d5db"), 1))
        for tick in range(-5, 3):
            tx = map_x(tick)
            painter.drawLine(QPointF(tx, top), QPointF(tx, top + row_h * len(self.rows)))
            painter.setPen(QColor("#475569"))
            painter.drawText(QRectF(tx - 12, top - 18, 24, 16), Qt.AlignCenter, str(tick))
            painter.setPen(QPen(QColor("#d1d5db"), 1))

        painter.setPen(QPen(QColor("#dc2626"), 1.4))
        painter.drawLine(QPointF(normal_x, top), QPointF(normal_x, top + row_h * len(self.rows)))
        painter.setPen(QColor("#dc2626"))
        painter.drawText(QRectF(normal_x + 4, top - 18, 90, 16), Qt.AlignLeft | Qt.AlignVCenter, self.threshold_label)

        zero_x = map_x(0)
        painter.setPen(QPen(QColor("#111827"), 1.2))
        painter.drawLine(QPointF(zero_x, top), QPointF(zero_x, top + row_h * len(self.rows)))

        for row_idx, (label, pre, post) in enumerate(self.rows):
            y = top + row_idx * row_h
            cy = y + row_h / 2
            painter.setPen(QColor("#111827"))
            painter.drawText(QRectF(8, y, label_w - 8, row_h), Qt.AlignLeft | Qt.AlignVCenter, label)
            painter.setPen(QPen(QColor("#cbd5e1"), 1))
            painter.drawLine(QPointF(left, cy), QPointF(right, cy))
            if pre is not None:
                painter.setBrush(QColor("#2563eb"))
                painter.setPen(Qt.NoPen)
                painter.drawEllipse(QPointF(map_x(pre), cy), 4, 4)
            if post is not None:
                painter.setBrush(QColor("#dc2626"))
                painter.setPen(Qt.NoPen)
                painter.drawEllipse(QPointF(map_x(post), cy), 4, 4)

        legend_y = self.height() - 20
        painter.setBrush(QColor("#2563eb"))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(QPointF(left + 4, legend_y + 5), 4, 4)
        painter.setBrush(QColor("#dc2626"))
        painter.drawEllipse(QPointF(left + 62, legend_y + 5), 4, 4)
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QColor("#374151"))
        painter.drawText(QRectF(left + 12, legend_y, 42, 16), Qt.AlignLeft | Qt.AlignVCenter, "PRE")
        painter.drawText(QRectF(left + 70, legend_y, 48, 16), Qt.AlignLeft | Qt.AlignVCenter, "POST")
