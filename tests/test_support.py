"""Shared test helpers compatible with the Python 3.10 shipped by Mint 21."""
from contextlib import contextmanager
import os


def layout_test_desktop(widget):
    """Host a resizable UI without the native desktop limiting its dimensions.

    Windows CI can have a 1024px desktop. A top-level window is then clamped
    by the window manager even when the test requests 1366px. As a child,
    the UI keeps its normal layouts/minimum sizes and can be resized freely.
    The caller must retain and close the returned host after closing the UI.
    """
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QWidget
    desktop = QWidget()
    desktop.setAttribute(Qt.WA_DontShowOnScreen)
    desktop.resize(1920, 1080)
    widget.setParent(desktop, Qt.Widget)
    desktop.show()
    return desktop


@contextmanager
def working_directory(path):
    previous = os.getcwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


@contextmanager
def loaded_pdf(path):
    """Release the PDF file even if a text/layout assertion fails on Windows."""
    from PySide6.QtPdf import QPdfDocument
    document = QPdfDocument()
    try:
        error = document.load(str(path))
        if error != QPdfDocument.Error.None_:
            raise AssertionError(f'No se pudo cargar el PDF de prueba: {error}')
        yield document
    finally:
        document.close()
