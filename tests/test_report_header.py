import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import unittest

from PySide6.QtGui import QColor, QImage, QPainter, QPalette
from PySide6.QtWidgets import QApplication
from app.report import SpirometryReportRenderer


class HeaderPrintTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt=QApplication.instance() or QApplication([])

    def test_header_default_prints_dark_in_dark_theme_and_keeps_explicit_color(self):
        previous=self.qt.palette()
        dark=QPalette(previous)
        dark.setColor(QPalette.Text,QColor('#ffffff'))
        dark.setColor(QPalette.WindowText,QColor('#ffffff'))
        self.qt.setPalette(dark)
        try:
            image=QImage(800,150,QImage.Format_ARGB32)
            image.fill(0xffffffff)
            painter=QPainter(image)
            renderer=SpirometryReportRenderer({'title':'Informe',
                'header_html':'<p style="font-size:24pt;font-weight:700">ENCABEZADO</p>'
                              '<p><span style="color:#b91c1c">Texto con color configurado</span></p>'})
            renderer.scale=1.
            renderer._draw_header(painter,10,10,780)
            painter.end()
            pixels=[image.pixelColor(x,y) for y in range(image.height()) for x in range(image.width())]
            self.assertGreater(sum(c.red()<80 and c.green()<80 and c.blue()<80 for c in pixels),100)
            self.assertGreater(sum(c.red()>120 and c.green()<80 and c.blue()<80 for c in pixels),20)
        finally:
            self.qt.setPalette(previous)


if __name__=='__main__':unittest.main()
