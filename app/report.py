from pathlib import Path

from PySide6.QtCore import QSizeF, QRectF, Qt
from PySide6.QtGui import QAbstractTextDocumentLayout, QColor, QFont, QFontMetrics, QImage, QPainter, QPalette, QPen, QTextDocument


class SpirometryReportRenderer:
    def __init__(self, payload):
        self.payload = payload

    def render(self, painter, page_rect):
        self.painter = painter
        self.page_rect = page_rect
        self.scale = page_rect.width() / 595.0
        self.left_margin = self._mm(self.payload.get("margin_left_mm", 12))
        self.top_margin = self._mm(self.payload.get("margin_top_mm", 6))
        self.right_margin = self._mm(self.payload.get("margin_right_mm", 12))
        self.bottom_margin = self._mm(self.payload.get("margin_bottom_mm", 12))
        x, y, width, bottom = self._page_content_rect()

        painter.save()
        painter.setPen(QColor("#111827"))
        y = self._draw_header(painter, x, y, width)
        y = self._draw_patient_block(painter, x, y + self._u(6), width)
        y = self._draw_summary_table(painter, x, y + self._u(16), width)
        note = self.payload.get("reference_note")
        if note:
            painter.setFont(QFont(painter.font().family(), 8))
            rect = QRectF(x, y + self._u(4), width, self._u(40))
            bounds = painter.boundingRect(rect, Qt.TextWordWrap, note)
            painter.drawText(bounds, Qt.TextWordWrap, note)
            y = bounds.bottom()
        y = self._draw_zscore_chart(painter, x, y + self._mm(2), width)
        y = self._draw_charts(painter, x, y + self._mm(2), width)
        self._draw_report_text(painter, x, y + self._mm(3), width, bottom)
        self._draw_respiratory_pages(painter)
        painter.restore()

    def _draw_respiratory_pages(self,painter):
        for entry in self.payload.get("respiratory_charts",[]):
            device=painter.device()
            if not hasattr(device,"newPage") or not device.newPage():
                break
            x,y,width,bottom=self._page_content_rect()
            y=self._draw_header(painter,x,y,width)+self._u(12)
            y=self._draw_patient_block(painter,x,y,width,reference_label=entry.get("reference_label","Sin referencia"))+self._u(16)
            painter.setFont(QFont(painter.font().family(),12,QFont.Bold))
            painter.drawText(QRectF(x,y,width,self._u(22)),Qt.AlignLeft,
                             entry["kind"].upper()+" · "+entry["phase"].upper()+" · curva seleccionada")
            y+=self._u(30)
            keys=(("svc","SVC","L"),("ic","IC","L"),("erv","ERV","L"),("vt","VT","L")) if entry["kind"]=="svc" else (("mvv","MVV","L/min"),("vt","VT","L"),("frequency","FR","min⁻¹"),("interval_seconds","Intervalo","s"))
            text=" · ".join(label+": "+("–" if entry["result"].get(key) is None else f"{entry['result'][key]:.2f} {unit}") for key,label,unit in keys)
            painter.setFont(QFont(painter.font().family(),9))
            painter.drawText(QRectF(x,y,width,self._u(40)),Qt.TextWordWrap,text)
            y+=self._u(45)
            image=entry["image"]
            height=min(width*image.height()/image.width(),bottom-y-self._u(45))
            painter.drawImage(QRectF(x,y,width,height),image)
            y+=height+self._u(10)
            painter.setFont(QFont(painter.font().family(),8))
            note="Resultados de esta curva. "+entry.get("reference","Sin referencia SVC/MVV configurada")+" Selección revisada por el operador."
            if entry["result"].get("warnings"):
                note+=" "+"; ".join(entry["result"]["warnings"])
            painter.drawText(QRectF(x,y,width,bottom-y),Qt.TextWordWrap,note)

    def _page_content_rect(self):
        x = self.page_rect.x() + self.left_margin
        y = self.page_rect.y() + self.top_margin
        width = self.page_rect.width() - self.left_margin - self.right_margin
        bottom = self.page_rect.bottom() - self.bottom_margin
        return x, y, width, bottom

    def _draw_header(self, painter, x, y, width):
        logo_path = self.payload.get("header_logo_path") or ""
        header_html = self.payload.get("header_html") or ""
        logo_w = self._u(58) if logo_path else 0
        gap = self._u(12) if logo_path else 0
        html_scale = self.scale * 0.75
        min_header_h = self._u(28)
        max_header_h = self._u(96)
        doc = None
        doc_width = max(1.0, (width - logo_w - gap) / html_scale)
        header_h = min_header_h
        if header_html:
            doc = QTextDocument()
            doc.setDocumentMargin(0)
            doc.setDefaultStyleSheet(
                "p, h1, h2, h3, h4, h5, h6 { margin-top: 0; margin-bottom: 0; }"
            )
            doc.setHtml(header_html)
            doc.setTextWidth(doc_width)
            header_h = min(max_header_h, max(min_header_h, doc.size().height() * html_scale))

        if logo_path and Path(logo_path).exists():
            image = QImage(logo_path)
            if not image.isNull():
                scaled = image.size()
                scaled.scale(QSizeF(logo_w, header_h).toSize(), Qt.KeepAspectRatio)
                image_rect = QRectF(x, y + (header_h - scaled.height()) / 2, scaled.width(), scaled.height())
                painter.drawImage(image_rect, image)

        if doc is not None:
            doc_height = header_h / html_scale
            painter.save()
            painter.translate(x + logo_w + gap, y)
            painter.scale(html_scale, html_scale)
            # QTextDocument otherwise inherits the dark desktop's light text.
            # Set the print default independently; preserve explicit rich-text colors.
            context = QAbstractTextDocumentLayout.PaintContext()
            context.palette.setColor(QPalette.Text, QColor('#111827'))
            context.clip = QRectF(0, 0, doc_width, doc_height)
            painter.setClipRect(context.clip)
            doc.documentLayout().draw(painter, context)
            painter.restore()
        else:
            painter.setFont(QFont(painter.font().family(), 16, QFont.Bold))
            painter.drawText(QRectF(x + logo_w + gap, y, width - logo_w - gap, self._u(28)), Qt.AlignCenter, self.payload["title"])
        return y + header_h

    def _draw_patient_block(self, painter, x, y, width, reference_label=None):
        patient = self.payload["patient"]
        session = self.payload["session"]
        columns = [
            [
                ("Paciente", f"{patient['first_name']} {patient['last_name']}"),
                ("DNI", patient["dni"] or "-"),
                ("Fecha Nac.", self.payload["birth_date"]),
                ("Edad", self.payload["age"]),
                ("Sexo", self.payload["sex"]),
            ],
            [
                ("Peso", f"{self._fmt_value(session['weight_kg'])} kg"),
                ("Altura", f"{self._fmt_value(session['height_cm'])} cm"),
            ],
            [
                ("", self.payload["study_datetime"]),
                ("Ref.", reference_label or self.payload.get("reference_label", "GLI-2012")),
            ],
        ]
        line_h = self._u(16)
        gap = self._u(18)
        col_widths = [width * 0.45, width * 0.22, width * 0.33 - gap * 2]
        col_x = [x, x + col_widths[0] + gap, x + col_widths[0] + col_widths[1] + gap * 2]
        max_rows = max(len(column) for column in columns)
        family = painter.font().family()
        for col, items in enumerate(columns):
            for row, (label, value) in enumerate(items):
                rect = QRectF(col_x[col], y + row * line_h, col_widths[col], line_h)
                if label:
                    painter.setFont(QFont(family, 9, QFont.Bold))
                    label_width = self._u(58 if col == 0 else 46)
                    painter.drawText(QRectF(rect.x(), rect.y(), label_width, rect.height()), Qt.AlignLeft | Qt.AlignVCenter, f"{label}:")
                    painter.setFont(QFont(family, 9))
                    painter.drawText(rect.adjusted(label_width, 0, 0, 0), Qt.AlignLeft | Qt.AlignVCenter, value)
                else:
                    painter.setFont(QFont(family, 9))
                    painter.drawText(rect, Qt.AlignLeft | Qt.AlignVCenter, value)
        return y + max_rows * line_h

    def _draw_summary_table(self, painter, x, y, width):
        headers = self.payload["summary_headers"]
        rows = self.payload["summary_rows"]
        red_cells = self.payload.get("summary_red_cells", [])
        row_h = self._u(22)
        col_count = len(headers)
        col_w = width / col_count
        family = painter.font().family()
        painter.setFont(QFont(family, 8, QFont.Bold))
        painter.setPen(QPen(QColor("#000000"), 1))
        painter.fillRect(QRectF(x, y, width, row_h), QColor("#000000"))
        for col, header in enumerate(headers):
            rect = QRectF(x + col * col_w, y, col_w, row_h)
            painter.drawRect(rect)
            painter.setPen(QColor("#ffffff"))
            painter.drawText(rect.adjusted(4, 0, -4, 0), Qt.AlignCenter, header)
            painter.setPen(QPen(QColor("#000000"), 1))
        for row_idx, row in enumerate(rows, start=1):
            if row_idx % 2 == 0:
                painter.fillRect(QRectF(x, y + row_idx * row_h, width, row_h), QColor("#f3f4f6"))
            for col, value in enumerate(row):
                rect = QRectF(x + col * col_w, y + row_idx * row_h, col_w, row_h)
                painter.setPen(QPen(QColor("#000000"), 1))
                painter.drawRect(rect)
                marked = (row_idx-1 < len(red_cells) and col < len(red_cells[row_idx-1])
                          and red_cells[row_idx-1][col])
                painter.setPen(QColor("#b91c1c" if marked else "#000000"))
                painter.setFont(QFont(family, 8, QFont.Bold if col == 0 else QFont.Normal))
                align = Qt.AlignLeft | Qt.AlignVCenter if col == 0 else Qt.AlignCenter
                painter.drawText(rect.adjusted(self._u(6), 0, -self._u(4), 0), align, value)
        return y + (len(rows) + 1) * row_h

    def _draw_zscore_chart(self, painter, x, y, width):
        rows = self.payload["zscore_rows"]
        if not rows:
            return y
        label_w = self._u(72)
        chart_x = x + label_w
        chart_w = width - label_w
        row_h = self._u(15)
        axis_min = -5.0
        axis_max = 2.0

        def map_x(value):
            return chart_x + ((value - axis_min) / (axis_max - axis_min)) * chart_w

        family = painter.font().family()
        painter.setFont(QFont(family, 9, QFont.Bold))
        painter.setPen(QColor("#111827"))
        painter.drawText(QRectF(x, y, width, self._u(16)), Qt.AlignLeft | Qt.AlignVCenter, "Z-score")
        y += self._u(18)

        normal_x = map_x(-1.645)
        painter.fillRect(QRectF(normal_x, y, chart_x + chart_w - normal_x, row_h * len(rows)), QColor("#dcfce7"))
        painter.setPen(QPen(QColor("#9ca3af"), 1))
        for tick in range(-5, 3):
            tx = map_x(tick)
            painter.drawLine(tx, y, tx, y + row_h * len(rows))
            painter.drawText(QRectF(tx - self._u(10), y - self._u(14), self._u(20), self._u(12)), Qt.AlignCenter, str(tick))
        painter.setPen(QPen(QColor("#dc2626"), 1.2))
        painter.drawLine(normal_x, y, normal_x, y + row_h * len(rows))
        painter.setPen(QPen(QColor("#111827"), 1.2))
        zero_x = map_x(0)
        painter.drawLine(zero_x, y, zero_x, y + row_h * len(rows))

        for row_idx, (label, pre, post) in enumerate(rows):
            cy = y + row_idx * row_h + row_h / 2
            painter.setPen(QColor("#111827"))
            painter.setFont(QFont(family, 8))
            painter.drawText(QRectF(x, y + row_idx * row_h, label_w - self._u(8), row_h), Qt.AlignLeft | Qt.AlignVCenter, label)
            painter.setPen(QPen(QColor("#d1d5db"), 1))
            painter.drawLine(chart_x, cy, chart_x + chart_w, cy)
            if pre is not None:
                painter.setBrush(QColor("#2563eb"))
                painter.setPen(Qt.NoPen)
                painter.drawEllipse(map_x(pre) - self._u(3), cy - self._u(3), self._u(6), self._u(6))
            if post is not None:
                painter.setBrush(QColor("#dc2626"))
                painter.setPen(Qt.NoPen)
                painter.drawEllipse(map_x(post) - self._u(3), cy - self._u(3), self._u(6), self._u(6))
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QColor("#374151"))
        legend_y = y + row_h * len(rows) + self._u(4)
        painter.setBrush(QColor("#2563eb"))
        painter.drawEllipse(chart_x, legend_y, self._u(6), self._u(6))
        painter.setBrush(QColor("#dc2626"))
        painter.drawEllipse(chart_x + self._u(40), legend_y, self._u(6), self._u(6))
        painter.setBrush(Qt.NoBrush)
        painter.drawText(QRectF(chart_x + self._u(10), legend_y - self._u(4), self._u(28), self._u(12)), Qt.AlignLeft, "PRE")
        painter.drawText(QRectF(chart_x + self._u(50), legend_y - self._u(4), self._u(34), self._u(12)), Qt.AlignLeft, "POST")
        painter.setPen(QColor("#dc2626"))
        painter.drawText(
            QRectF(normal_x + self._u(4), y - self._u(14), self._u(80), self._u(12)),
            Qt.AlignLeft,
            self.payload.get("zscore_threshold_label", "LLN"),
        )
        return legend_y + self._u(12)

    def _draw_charts(self, painter, x, y, width):
        gap = self._u(16)
        chart_h = self._u(210)
        chart_w = (width - gap) / 2
        for idx, image in enumerate(self.payload["charts"]):
            rect = QRectF(x + idx * (chart_w + gap), y, chart_w, chart_h)
            painter.drawImage(rect, image)
        return y + chart_h

    def _draw_report_text(self, painter, x, y, width, bottom):
        family = painter.font().family()
        title_font = QFont(family, 9, QFont.Bold)
        body_font = QFont(family, 8)
        text = self.payload["report_text"] or ""
        paragraphs = text.splitlines() or [""]
        painter.setFont(body_font)
        lines = self._wrap_text_lines(paragraphs, painter.fontMetrics(), width)
        index = self._draw_report_lines(painter, x, y, width, bottom, lines, 0, title_font, body_font, "Informe")
        while index < len(lines):
            device = painter.device()
            if not hasattr(device, "newPage") or not device.newPage():
                break
            x, y, width, bottom = self._page_content_rect()
            painter.setPen(QColor("#111827"))
            y = self._draw_header(painter, x, y, width)
            index = self._draw_report_lines(
                painter,
                x,
                y + self._mm(5),
                width,
                bottom,
                lines,
                index,
                title_font,
                body_font,
                "Informe",
            )

    def _draw_report_lines(self, painter, x, y, width, bottom, lines, start, title_font, body_font, title):
        painter.setPen(QColor("#000000"))
        painter.setFont(title_font)
        title_h = self._u(15)
        painter.drawText(QRectF(x, y, width, title_h), Qt.AlignLeft | Qt.AlignVCenter, title)
        y += title_h + self._u(2)
        painter.setFont(body_font)
        fm = painter.fontMetrics()
        line_h = fm.lineSpacing() * 1.02
        idx = start
        while idx < len(lines) and y + line_h <= bottom:
            painter.drawText(QRectF(x, y, width, line_h), Qt.AlignLeft | Qt.AlignVCenter, lines[idx])
            y += line_h
            idx += 1
        return idx

    def _wrap_text_lines(self, paragraphs, fm, width):
        lines = []
        for paragraph in paragraphs:
            if not paragraph.strip():
                lines.append("")
                continue
            current = ""
            for word in paragraph.split():
                candidate = word if not current else f"{current} {word}"
                if fm.horizontalAdvance(candidate) <= width:
                    current = candidate
                else:
                    if current:
                        lines.append(current)
                    current = word
            if current:
                lines.append(current)
        return lines or [""]

    @staticmethod
    def _fmt_value(value):
        return "-" if value is None else f"{value:.1f}"

    def _u(self, value):
        return value * self.scale

    def _mm(self, value):
        return self._u(value * 72.0 / 25.4)
