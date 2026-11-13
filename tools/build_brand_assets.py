"""Resize the supplied NeumoFlow PNG to PNG and a Windows ICO at native icon sizes.

Run from the project root: QT_QPA_PLATFORM=offscreen python tools/build_brand_assets.py
Requires the application's existing PySide6 dependency, no imaging extras.
"""
import struct
from pathlib import Path
from PySide6.QtCore import QByteArray, QBuffer, QIODevice, Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication


def build():
    app = QApplication.instance() or QApplication([])
    root = Path(__file__).resolve().parent.parent / 'app/data/brand'
    source = QImage(str(root / 'neumoflow-transparent.png'))
    if source.isNull():
        raise ValueError('Invalid NeumoFlow source PNG')
    frames = []
    sizes = (16, 24, 32, 48, 64, 128, 256)
    for size in sizes:
        image = source.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.WriteOnly)
        if not image.save(buffer, 'PNG'):
            raise RuntimeError('Could not encode logo')
        frames.append(bytes(data))
        if size == 256:
            (root / 'neumoflow.png').write_bytes(bytes(data))
    offset = 6 + 16 * len(sizes)
    directory = bytearray(struct.pack('<HHH', 0, 1, len(sizes)))
    for size, frame in zip(sizes, frames):
        directory.extend(struct.pack('<BBBBHHII', size % 256, size % 256, 0, 0, 1, 32, len(frame), offset))
        offset += len(frame)
    (root / 'neumoflow.ico').write_bytes(bytes(directory) + b''.join(frames))


if __name__ == '__main__':
    build()
