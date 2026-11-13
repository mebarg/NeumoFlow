import sys

from PySide6.QtWidgets import QApplication

from app.main_window import MainWindow
from app.branding import APP_NAME, app_icon


def main():
    if len(sys.argv)==3 and sys.argv[1]=='--self-test':
        from app.smoke_test import run
        return run(sys.argv[2])
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setWindowIcon(app_icon())
    window = MainWindow()
    window.showMaximized()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
