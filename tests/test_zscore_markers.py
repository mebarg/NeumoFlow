"""PRE/POST remain distinguishable on screen, paper and grayscale copies."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import unittest
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication
from app.charts import ZScoreWidget
from app.report import SpirometryReportRenderer


class ZscoreMarkerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])

    def assert_phase_symbols(self, image, pre, post, radius):
        self.assertEqual(image.pixelColor(round(pre[0]), round(pre[1])).name(), '#2563eb')
        self.assertNotEqual(image.pixelColor(round(post[0]), round(post[1])).name(), '#dc2626')
        colors = {image.pixelColor(x, y).name()
                  for x in range(round(post[0])-radius, round(post[0])+radius+1)
                  for y in range(round(post[1])-radius, round(post[1])+radius+1)}
        self.assertIn('#dc2626', colors)
        gray = image.convertToFormat(QImage.Format_Grayscale8)
        self.assertLess(gray.pixelColor(round(pre[0]), round(pre[1])).red(), 160)
        self.assertGreater(gray.pixelColor(round(post[0]), round(post[1])).red(), 180)

    def test_screen_points_legend_and_coincident_values(self):
        chart = ZScoreWidget()
        try:
            chart.resize(800, 170)
            chart.set_rows([('FVC', -2., -1.)])
            image = QImage(chart.size(), QImage.Format_ARGB32)
            chart.render(image)
            left, right = 96, 782
            map_x = lambda z: left + (z+5)/7*(right-left)
            self.assert_phase_symbols(image, (map_x(-2), 91), (map_x(-1), 91), 8)
            self.assert_phase_symbols(image, (left+4, 155), (left+62, 155), 8)
            chart.set_rows([('FVC', -2., -2.)])
            chart.render(image)
            self.assertEqual(image.pixelColor(round(map_x(-2)), 91).name(), '#2563eb')
            self.assertIn('#dc2626', {image.pixelColor(round(map_x(-2))+dx, 91).name() for dx in range(-8, 9)})
        finally:
            chart.close()

    def test_printed_points_and_legend_match_screen_in_grayscale(self):
        image = QImage(1100, 300, QImage.Format_ARGB32)
        image.fill(QColor('white'))
        renderer = SpirometryReportRenderer({'zscore_rows': [('FVC', -2., -1.)]})
        renderer.scale = 2.
        painter = QPainter(image)
        try:
            painter.setRenderHint(QPainter.Antialiasing)
            renderer._draw_zscore_chart(painter, 20., 30., 900.)
        finally:
            painter.end()
        chart_x, chart_w = 164, 756
        map_x = lambda z: chart_x + (z+5)/7*chart_w
        self.assert_phase_symbols(image, (map_x(-2), 81), (map_x(-1), 81), 12)
        self.assert_phase_symbols(image, (chart_x+6, 110), (chart_x+86, 110), 12)
