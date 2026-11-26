"""Shared desktop presentation, independent of the operating system's theme."""
from pathlib import Path
from app.ui_icons import refresh_button_icon, light_icon, LightFileIconProvider, set_button_icon, contrast_dialog_icon
from PySide6.QtCore import Signal, Qt, QObject, QEvent
from PySide6.QtGui import QColor, QFont, QPalette, QAction
from PySide6.QtWidgets import QLabel, QWidget, QHBoxLayout, QPushButton, QButtonGroup, QFileDialog, QStyleFactory, QToolButton, QDialogButtonBox, QStyle, QComboBox, QApplication, QDialog, QAbstractButton, QStyledItemDelegate, QStyleOptionViewItem


class PhaseTableDelegate(QStyledItemDelegate):
    """Keep predicted/stage/summary row colors visible under the application stylesheet."""
    def paint(self, painter, option, index):
        brush=index.data(Qt.BackgroundRole)
        if index.siblingAtColumn(0).data() or brush is None:
            return super().paint(painter,option,index)
        styled=QStyleOptionViewItem(option)
        self.initStyleOption(styled,index)
        painter.save()
        painter.setClipRect(option.rect)
        painter.fillRect(option.rect,brush)
        painter.setFont(styled.font)
        foreground=index.data(Qt.ForegroundRole)
        painter.setPen(foreground.color() if foreground is not None else QColor('#1f2937'))
        alignment=Qt.AlignmentFlag(index.data(Qt.TextAlignmentRole) or Qt.AlignCenter)
        text=styled.fontMetrics.elidedText(styled.text,Qt.ElideRight,max(0,option.rect.width()-12))
        painter.drawText(option.rect.adjusted(6,0,-6,0),alignment,text)
        painter.setPen(QColor('#dce5ea'))
        painter.drawLine(option.rect.bottomLeft(),option.rect.bottomRight())
        painter.restore()


class PhaseSelector(QWidget):
    """Native, keyboard-focusable segmented selector with the old data API."""
    currentIndexChanged = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('phaseControl')
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName('Fase del estudio')
        self._items = []
        self._disabled_indices = set()
        self._index = -1
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(3, 3, 3, 3)
        self._layout.setSpacing(3)
        self._group = QButtonGroup(self)
        self._group.idClicked.connect(self.setCurrentIndex)

    def addItem(self, label, data):
        index = len(self._items)
        button = role(QPushButton(label), 'phase')
        button.setCheckable(True)
        self._group.addButton(button, index)
        self._layout.addWidget(button)
        self._items.append((data, button))
        if self._index < 0:
            self.setCurrentIndex(0)

    def findData(self, value):
        return next((i for i, (data, _) in enumerate(self._items) if data == value), -1)

    def currentData(self):
        return self._items[self._index][0] if self._index >= 0 else None

    def setItemEnabled(self, index, enabled):
        if not 0 <= index < len(self._items):
            return
        if enabled:
            self._disabled_indices.discard(index)
        else:
            self._disabled_indices.add(index)
        self._items[index][1].setEnabled(enabled)

    def setItemToolTip(self, index, text):
        self._items[index][1].setToolTip(text)

    def setCurrentIndex(self, index):
        if index == self._index or not 0 <= index < len(self._items) or index in self._disabled_indices:
            return
        self._index = index
        self._items[index][1].setChecked(True)
        self.currentIndexChanged.emit(index)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Left, Qt.Key_Right):
            self.setCurrentIndex((self._index + (1 if event.key() == Qt.Key_Right else -1)) % len(self._items))
            event.accept()
        else:
            super().keyPressEvent(event)


class StatusLabel(QLabel):
    """Keep acquisition messages readable with a semantic, text-backed color."""
    def __init__(self, text='', parent=None):
        super().__init__(parent)
        self.setProperty('role', 'status')
        self.setWordWrap(True)
        self.setText(text)

    def setText(self, text):
        super().setText(text)
        lower = text.lower()
        state = ('error' if any(s in lower for s in ('error', 'repetir puesta', 'no se detect')) else
                 'recording' if any(s in lower for s in ('capturando', 'iniciando captura', 'finalizando')) else
                 'working' if any(s in lower for s in ('puesta a cero', 'liberando', 'preparando')) else 'ready')
        if self.property('state') != state:
            self.setProperty('state', state)
            repolish(self)


def apply_theme(window):
    palette = QPalette(window.palette())
    for role, value in ((QPalette.Window, '#f3f6f8'), (QPalette.WindowText, '#20303d'),
                        (QPalette.Base, '#ffffff'), (QPalette.AlternateBase, '#f8fafb'),
                        (QPalette.Text, '#20303d'), (QPalette.Button, '#ffffff'),
                        (QPalette.ButtonText, '#20303d'), (QPalette.Highlight, '#dcefee'),
                        (QPalette.HighlightedText, '#163b40'), (QPalette.ToolTipBase, '#ffffff'),
                        (QPalette.ToolTipText, '#20303d'), (QPalette.PlaceholderText, '#657580')):
        palette.setColor(role, QColor(value))
    window.setPalette(palette)
    window.setFont(QFont('Segoe UI', 10))
    window.setStyleSheet(STYLESHEET)


def apply_dialog_theme(dialog):
    if not hasattr(dialog, '_light_style'):
        dialog._light_style = QStyleFactory.create('Fusion')
    dialog.setStyle(dialog._light_style)
    apply_theme(dialog)
    preview_icons = {'fitWidthAction': 'fit-width', 'fitPageAction': 'fit-page',
                     'singleModeAction': 'page', 'facingModeAction': 'pages',
                     'overviewModeAction': 'grid'}
    for action in dialog.findChildren(QAction):
        if action.objectName() in preview_icons:
            action.setProperty('iconKind', preview_icons[action.objectName()])
        contrast_dialog_icon(action)
    for child in dialog.findChildren(QWidget):
        child.setStyle(dialog._light_style)
        if isinstance(child, QAbstractButton) and not (isinstance(child, QToolButton) and child.defaultAction() is not None):
            contrast_dialog_icon(child)


class DialogThemeFilter(QObject):
    """Theme app-owned dialogs and the separate windows used by combo boxes."""
    def eventFilter(self, watched, event):
        if (event.type() == QEvent.Show and isinstance(watched, QWidget)
                and watched.isWindow() and isinstance(watched.parentWidget(), QComboBox)):
            owner = watched.parentWidget()
            while owner is not None and owner is not self.parent():
                owner = owner.parentWidget()
            if owner is self.parent():
                palette = QPalette(watched.palette())
                for color_role, color in ((QPalette.Window, '#ffffff'), (QPalette.Base, '#ffffff'),
                                          (QPalette.Text, '#20303d'), (QPalette.WindowText, '#20303d'),
                                          (QPalette.Highlight, '#dcefee'), (QPalette.HighlightedText, '#163b40')):
                    palette.setColor(color_role, QColor(color))
                watched.setPalette(palette)
                watched.setAutoFillBackground(True)
        if event.type() == QEvent.Show and isinstance(watched, QDialog):
            owner = watched.parentWidget()
            while owner is not None and owner is not self.parent():
                owner = owner.parentWidget()
            if owner is self.parent():
                apply_dialog_theme(watched)
        return False


def install_dialog_theme(window):
    window._dialog_theme_filter = DialogThemeFilter(window)
    QApplication.instance().installEventFilter(window._dialog_theme_filter)


def file_dialog(parent, title, name_filter, suggested='', save=False):
    """Use a fully themed Qt chooser instead of mixing native dark surfaces."""
    dialog = QFileDialog(parent, title)
    dialog.setOption(QFileDialog.DontUseNativeDialog, True)
    dialog._light_style = QStyleFactory.create('Fusion')
    dialog.setStyle(dialog._light_style)
    for child in dialog.findChildren(QWidget):
        child.setStyle(dialog._light_style)
    apply_theme(dialog)
    dialog.setNameFilter(name_filter)
    dialog.setAcceptMode(QFileDialog.AcceptSave if save else QFileDialog.AcceptOpen)
    dialog.setFileMode(QFileDialog.AnyFile if save else QFileDialog.ExistingFile)
    dialog._file_icons = LightFileIconProvider()
    dialog.setIconProvider(dialog._file_icons)
    navigation_icons = {'backButton': 'left', 'forwardButton': 'right',
                        'toParentButton': 'up', 'newFolderButton': 'folder-add',
                        'listModeButton': 'list', 'detailModeButton': 'grid'}
    for button in dialog.findChildren(QToolButton):
        if button.objectName() in navigation_icons:
            button.setIcon(light_icon(navigation_icons[button.objectName()]))
    for box in dialog.findChildren(QDialogButtonBox):
        for standard, icon in ((QDialogButtonBox.Save, QStyle.SP_DialogSaveButton),
                               (QDialogButtonBox.Open, QStyle.SP_DialogOpenButton),
                               (QDialogButtonBox.Cancel, QStyle.SP_DialogCancelButton)):
            button = box.button(standard)
            if button is not None:
                set_button_icon(button, icon)
    if suggested:
        dialog.selectFile(suggested)
    location = dialog.findChild(QComboBox, 'lookInCombo')
    if location is not None:
        def update_location_icons(*_args):
            for index in range(location.count()):
                location.setItemIcon(index, light_icon('folder'))
        update_location_icons()
        dialog.directoryEntered.connect(update_location_icons)
        location.model().rowsInserted.connect(update_location_icons)
    return dialog


def role(widget, value):
    widget.setProperty('role', value)
    refresh_button_icon(widget)
    return widget


def repolish(widget):
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


STYLESHEET = """
QMainWindow, QWidget#appRoot, QWidget#workspace { background: #f3f6f8; }
QWidget { color: #20303d; }
QDialog { background: #f3f6f8; color: #20303d; }
QDialog QToolBar { background: #f3f6f8; color: #20303d; border: none; }
QDialog QToolButton { background: #ffffff; color: #20303d;
    border: 1px solid #cedbe1; border-radius: 5px; padding: 5px; }
QDialog QToolButton:hover { background: #edf4f5; }
QDialog QToolButton:checked { background: #dcefee; }
QDialog QAbstractItemView { background: #ffffff; color: #20303d;
    alternate-background-color: #f8fafb; selection-background-color: #dcefee;
    selection-color: #163b40; }
QDialog QFrame#sidebar { background: #ffffff; color: #20303d; border: 1px solid #cedbe1; }
QMessageBox { background-color: #ffffff; color: #20303d; }
QMessageBox QLabel { background-color: transparent; color: #20303d; }
QMessageBox QDialogButtonBox { background-color: #ffffff; }
QMessageBox QPushButton { background-color: #ffffff; color: #20303d; }
QFileDialog { background: #f3f6f8; color: #20303d; }
QFileDialog QAbstractItemView { background: #ffffff; alternate-background-color: #f8fafb;
    color: #20303d; border: 1px solid #cedbe1;
    selection-background-color: #dcefee; selection-color: #163b40; }
QFileDialog QFrame#sidebar { background: #ffffff; color: #20303d; border: 1px solid #cedbe1; }
QFileDialog QToolButton { background: #ffffff; color: #20303d;
    border: 1px solid #cedbe1; border-radius: 5px; padding: 5px; }
QFileDialog QToolButton:hover { background: #edf4f5; }
QFileDialog QToolButton:checked { background: #dcefee; }
QWidget#phaseControl { background: #e7edef; border-radius: 7px; }
QLabel { background: transparent; }
QLabel[role="muted"] { color: #627480; font-size: 12px; }
QLabel[role="pageTitle"] { font-size: 24px; font-weight: 600; }
QLabel[role="sectionTitle"] { font-size: 14px; font-weight: 600; }
QLabel[role="eyebrow"] { color: #627480; font-size: 12px; }
QLabel[role="timer"] { font-size: 23px; font-weight: 500; min-width: 64px; }
QLabel[role="status"] { color: #087f83; background: #eaf5f4; border-radius: 6px; font-size: 12px; padding: 6px 10px; }
QLabel[role="status"][state="working"] { color: #8c6326; background: #fff4db; }
QLabel[role="status"][state="recording"] { color: #b02f3c; background: #fdebed; }
QLabel[role="status"][state="error"] { color: #b02f3c; background: #fdebed; }
QLabel[role="sessionQuality"] { color: #627480; background: #e7edef;
    border-radius: 6px; padding: 6px 10px; font-size: 12px; }
QLabel[role="sessionQuality"][state="progress"] { color: #805b20; background: #fff4db; }
QLabel[role="sessionQuality"][state="ready"] { color: #166534; background: #dcfce7; }

QFrame[role="surface"] { background: #ffffff; border: 1px solid #dfe7eb; border-radius: 10px; }
QFrame[role="surface"] QLabel { border: none; }
QFrame#sidebar { background: #162b36; border: none; }
QFrame#sidebar QLabel { color: #b6c8d1; }
QFrame#sidebar QLabel#brand { color: #ffffff; font-size: 16px; font-weight: 600; }
QFrame#sidebar QLabel#brandDetail { color: #9db2bd; font-size: 11px; }
QFrame#sidebar QPushButton { background: transparent; color: #cad8df; border: none;
    border-radius: 7px; text-align: left; padding: 11px 10px; font-size: 12px; }
QFrame#sidebar QPushButton:hover { background: #223e4a; color: #ffffff; }
QFrame#sidebar QPushButton:checked { background: #284650; color: #ffffff;
    border-left: 3px solid #64cdca; padding-left: 7px; }
QFrame#sidebar QPushButton:disabled { color: #8195a0; }
QFrame#sidebar QPushButton#newPatient { background: #087f83; color: #ffffff;
    text-align: center; border: 1px solid #269fa0; }
QFrame#sidebar QPushButton#newPatient:hover { background: #0c9094; }
QLabel#deviceStatus { color: #b6c8d1; font-size: 11px; }
QLabel#deviceStatus[state="ready"] { color: #87ddc7; }
QPushButton { background: #ffffff; color: #20303d; border: 1px solid #cedbe1;
    border-radius: 7px; padding: 8px 13px; min-height: 18px; }
QPushButton:hover { background: #edf4f5; border-color: #98b4bd; }
QPushButton:pressed { background: #deecef; }
QPushButton:focus { border-color: #087f83; }
QPushButton:disabled { color: #85949d; background: #edf1f3; border-color: #dbe3e7; }
QPushButton[role="primary"] { background: #087f83; border-color: #087f83;
    color: #ffffff; font-weight: 600; padding: 10px 17px; }
QPushButton[role="primary"]:hover { background: #076d72; }
QPushButton[role="primary"][recording="true"] { background: #b63845; border-color: #b63845; }
QPushButton[role="primary"]:disabled { background: #cbdadd; border-color: #cbdadd; color: #566d76; }
QPushButton[role="link"] { background: transparent; color: #087f83; border: none;
    padding: 4px 6px; font-size: 12px; }
QPushButton[role="studyTab"] { background: transparent; border: none; border-radius: 0;
    border-bottom: 2px solid transparent; color: #627480; padding: 7px 2px; }
QPushButton[role="studyTab"]:checked { color: #087f83; border-bottom-color: #087f83; }
QPushButton[role="phase"] { border: none; background: #e7edef; color: #526875;
    padding: 5px 15px; min-height: 18px; }
QPushButton[role="phase"]:checked { background: #ffffff; color: #087f83; border: 1px solid #cbdcde; }
QLineEdit, QSpinBox, QDoubleSpinBox, QDateEdit, QComboBox, QTextEdit { background: #ffffff;
    color: #20303d; border: 1px solid #cedbe1; border-radius: 6px; padding: 7px 9px;
    selection-background-color: #cce7e5; selection-color: #163b40; }
QLineEdit:focus, QTextEdit:focus, QComboBox:focus { border-color: #087f83; }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox[referenceSelector="true"]::down-arrow { image: url("@ICONS@/chevron-down.svg"); width: 16px; height: 16px; }
QComboBox QAbstractItemView { background: #ffffff; color: #20303d;
    border: none; outline: none;
    selection-background-color: #dcefee; selection-color: #163b40; }
QTableWidget { background: #ffffff; alternate-background-color: #f8fafb; color: #1f2937;
    border: 1px solid #dfe7eb; border-radius: 8px; gridline-color: #edf1f3;
    selection-background-color: #eaf5f4; selection-color: #163b40; }
QTableWidget::item { padding: 4px 6px; border-bottom: 1px solid #edf1f3; }
QTableWidget::item:selected { background: #eaf5f4; }
QTableWidget#maneuverTable { border: none; border-radius: 0; }
QHeaderView, QHeaderView > QWidget { background: #f7fafb; color: #526875; }
QHeaderView::section { background: #f7fafb; color: #526875; border: none;
    border-bottom: 1px solid #dfe7eb; padding: 9px 8px; font-size: 11px; font-weight: 500; }
QTableCornerButton, QTableCornerButton::section { background: #f7fafb; border: none; }
QGroupBox { background: #ffffff; border: 1px solid #dfe7eb; border-radius: 10px;
    margin-top: 14px; padding: 18px 12px 12px; font-weight: 600; }
QGroupBox::title { subcontrol-origin: margin; subcontrol-position: top left;
    padding: 0 6px; left: 14px; color: #334b58; }
QTabWidget::pane { background: #ffffff; border: 1px solid #dfe7eb; border-radius: 6px; }
QTabBar::tab { background: transparent; color: #627480; padding: 10px 13px;
    border-bottom: 2px solid transparent; }
QTabBar::tab:selected { color: #087f83; border-bottom-color: #087f83; }
QSplitter::handle { background: #e6edef; height: 5px; margin: 3px 0; }
QSplitter::handle:hover { background: #b3cfd1; }
QScrollArea { border: none; background: transparent; }
QWidget[scrollBackground="true"] { background: #f3f6f8; }
QScrollBar:vertical { background: #f3f6f8; width: 10px; margin: 0; }
QScrollBar::handle:vertical { background: #bdcdd5; border-radius: 4px; min-height: 26px; }
QScrollBar:horizontal { background: #f3f6f8; height: 10px; margin: 0; }
QScrollBar::handle:horizontal { background: #bdcdd5; border-radius: 4px; min-width: 26px; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QCheckBox { spacing: 7px; }
QCheckBox::indicator, QAbstractItemView::indicator {
    width: 16px; height: 16px; border: 1px solid #8195a0;
    border-radius: 3px; background: #ffffff; image: none; }
QCheckBox::indicator:checked, QAbstractItemView::indicator:checked {
    background: #e4f4f3; border-color: #087f83;
    image: url("@ICONS@/checkbox-checked.svg"); }
QCheckBox::indicator:indeterminate, QAbstractItemView::indicator:indeterminate {
    background: #e4f4f3; border-color: #087f83;
    image: url("@ICONS@/checkbox-partial.svg"); }
QCheckBox::indicator:hover, QAbstractItemView::indicator:hover {
    border-color: #087f83; background: #edf8f7; }
QCheckBox::indicator:disabled, QAbstractItemView::indicator:disabled {
    border-color: #adbdc6; background: #edf1f3; }
QCheckBox::indicator:checked:disabled, QAbstractItemView::indicator:checked:disabled {
    image: url("@ICONS@/checkbox-disabled.svg"); }
QToolTip { background: #ffffff; color: #20303d; border: 1px solid #b5c8d2; padding: 6px; }
""".replace('@ICONS@', (Path(__file__).resolve().parent / 'data' / 'icons').as_posix())
