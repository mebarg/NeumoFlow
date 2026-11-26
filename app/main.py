import argparse
import re
import sys

from PySide6.QtWidgets import QApplication

from app.main_window import MainWindow
from app.branding import APP_NAME, app_icon


def window_size(value):
    match = re.fullmatch(r'([1-9][0-9]{0,4})[xX]([1-9][0-9]{0,4})', value)
    if not match:
        raise argparse.ArgumentTypeError('Usar ANCHOxALTO, por ejemplo 1366x768.')
    return tuple(map(int, match.groups()))


def main(argv=None):
    parser = argparse.ArgumentParser(description='NeumoFlow')
    parser.add_argument('--window-size', type=window_size, metavar='ANCHOxALTO',
                        help='Abrir sin maximizar con este tamaño interior para probar la interfaz.')
    parser.add_argument('--self-test', metavar='INFORME_JSON', help=argparse.SUPPRESS)
    options, qt_args = parser.parse_known_args(sys.argv[1:] if argv is None else argv)
    if options.self_test:
        from app.smoke_test import run
        return run(options.self_test)
    app = QApplication([sys.argv[0], *qt_args])
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setWindowIcon(app_icon())
    window = MainWindow()
    if options.window_size:
        window.resize(*options.window_size)
        window.show()
    else:
        window.showMaximized()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
