"""NeumoFlow's display identity; independent of existing user data paths."""
from pathlib import Path
from PySide6.QtGui import QIcon

APP_NAME = "NeumoFlow"
ASSET_DIR = Path(__file__).resolve().parent / "data" / "brand"


def app_icon():
    return QIcon(str(ASSET_DIR / "neumoflow.ico"))
