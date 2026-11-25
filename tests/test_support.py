"""Shared test helpers compatible with the Python 3.10 shipped by Mint 21."""
from contextlib import contextmanager
import os


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
