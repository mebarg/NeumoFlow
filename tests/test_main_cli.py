import argparse
import unittest
from unittest.mock import patch
from app.main import main, window_size


class MainCliTests(unittest.TestCase):
    def test_window_size_accepts_dimensions_and_rejects_invalid_values(self):
        self.assertEqual(window_size('1366x768'), (1366, 768))
        for value in ('1366', '1366x0', '-1x768', '1366x768extra'):
            with self.subTest(value=value), self.assertRaises(argparse.ArgumentTypeError):
                window_size(value)

    def test_size_opens_unmaximized_and_normal_start_still_maximizes(self):
        for args in ([], ['--window-size', '1366x768']):
            with self.subTest(args=args), patch('app.main.QApplication') as application, \
                    patch('app.main.MainWindow') as window, patch('app.main.app_icon'):
                application.return_value.exec.return_value = 0
                self.assertEqual(main(args), 0)
                if args:
                    window.return_value.resize.assert_called_once_with(1366, 768)
                    window.return_value.show.assert_called_once()
                    window.return_value.showMaximized.assert_not_called()
                else:
                    window.return_value.showMaximized.assert_called_once()

    def test_self_test_still_runs_without_opening_the_window(self):
        with patch('app.smoke_test.run', return_value=0) as check, patch('app.main.QApplication') as application:
            self.assertEqual(main(['--self-test', 'test.json']), 0)
            check.assert_called_once_with('test.json')
            application.assert_not_called()
