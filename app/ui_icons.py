"""Small vector icons with explicit contrast, independent of the desktop theme."""
from PySide6.QtCore import Qt, QRect, QRectF, QFileInfo
from PySide6.QtGui import QColor, QIcon, QIconEngine, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QStyle, QFileIconProvider


KINDS = {
    QStyle.SP_FileIcon: 'add', QStyle.SP_DirHomeIcon: 'home',
    QStyle.SP_MediaPlay: 'play', QStyle.SP_MediaStop: 'stop',
    QStyle.SP_ComputerIcon: 'monitor', QStyle.SP_FileDialogDetailedView: 'sliders',
    QStyle.SP_BrowserReload: 'reset', QStyle.SP_TrashIcon: 'trash',
    QStyle.SP_ArrowForward: 'right', QStyle.SP_ArrowRight: 'right',
    QStyle.SP_ArrowBack: 'left', QStyle.SP_ArrowLeft: 'left',
    QStyle.SP_DialogSaveButton: 'save', QStyle.SP_DialogOpenButton: 'folder',
    QStyle.SP_FileDialogNewFolder: 'add', QStyle.SP_FileDialogContentsView: 'edit',
    QStyle.SP_DialogCancelButton: 'cancel', QStyle.SP_DialogApplyButton: 'check',
}


class LineIconEngine(QIconEngine):
    def __init__(self, kind, color, disabled):
        super().__init__()
        self.kind, self.color, self.disabled = kind, color, disabled

    def clone(self):
        return LineIconEngine(self.kind, self.color, self.disabled)

    def pixmap(self, size, mode, state):
        pixmap = QPixmap(size)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        self.paint(painter, QRect(0, 0, size.width(), size.height()), mode, state)
        painter.end()
        return pixmap

    def paint(self, painter, rect, mode, state):
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        side = min(rect.width(), rect.height())
        painter.translate(rect.center().x() - side / 2, rect.center().y() - side / 2)
        painter.scale(side / 24, side / 24)
        color = QColor(self.disabled if mode == QIcon.Disabled else self.color)
        painter.setPen(QPen(color, 1.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.setBrush(Qt.NoBrush)
        path = QPainterPath()
        def line(*points):
            path.moveTo(*points[0])
            for point in points[1:]:
                path.lineTo(*point)
        kind = self.kind
        if kind in ('play', 'stop'):
            painter.setBrush(color)
            if kind == 'play':
                line((7, 4), (20, 12), (7, 20), (7, 4))
            else:
                path.addRoundedRect(QRectF(5, 5, 14, 14), 1, 1)
        elif kind in ('left', 'right'):
            line((4, 12), (20, 12))
            x, back = (4, 10) if kind == 'left' else (20, 14)
            line((back, 6), (x, 12), (back, 18))
        elif kind == 'up':
            line((12, 20), (12, 4)); line((6, 10), (12, 4), (18, 10))
        elif kind == 'list':
            for y in (5, 12, 19):
                line((3, y), (5, y)); line((9, y), (21, y))
        elif kind == 'grid':
            for x in (4, 14):
                for y in (4, 14):
                    path.addRect(QRectF(x, y, 6, 6))
        elif kind in ('page', 'pages', 'fit-page', 'fit-width'):
            path.addRect(QRectF(6, 3, 12, 18))
            if kind == 'pages':
                line((3, 18), (3, 1), (15, 1))
            elif kind == 'fit-width':
                line((2, 12), (22, 12))
                line((5, 9), (2, 12), (5, 15))
                line((19, 9), (22, 12), (19, 15))
            elif kind == 'fit-page':
                line((3, 6), (3, 1), (8, 1)); line((16, 1), (21, 1), (21, 6))
                line((3, 18), (3, 23), (8, 23)); line((16, 23), (21, 23), (21, 18))
        elif kind == 'reset':
            path.arcMoveTo(QRectF(5, 5, 14, 14), 140)
            path.arcTo(QRectF(5, 5, 14, 14), 140, -300)
            line((3, 4), (3, 10), (9, 10))
        elif kind == 'trash':
            line((4, 6), (20, 6)); line((9, 6), (9, 3), (15, 3), (15, 6))
            line((6, 6), (7, 21), (17, 21), (18, 6))
            line((10, 10), (10, 17)); line((14, 10), (14, 17))
        elif kind == 'home':
            line((3, 11), (12, 3), (21, 11)); line((5, 10), (5, 21), (19, 21), (19, 10))
            line((9, 21), (9, 14), (15, 14), (15, 21))
        elif kind == 'monitor':
            path.addRoundedRect(QRectF(3, 4, 18, 13), 1, 1)
            line((12, 17), (12, 21)); line((8, 21), (16, 21))
        elif kind == 'sliders':
            for y, x in ((5, 8), (12, 16), (19, 10)):
                line((3, y), (x - 2, y)); line((x + 2, y), (21, y))
                path.addEllipse(QRectF(x - 2, y - 2, 4, 4))
        elif kind == 'save':
            line((4, 3), (17, 3), (21, 7), (21, 21), (3, 21), (3, 3), (4, 3))
            line((7, 3), (7, 9), (16, 9), (16, 3))
            line((7, 21), (7, 14), (17, 14), (17, 21))
        elif kind in ('folder', 'folder-add'):
            line((3, 8), (3, 5), (10, 5), (12, 8), (21, 8), (19, 20), (3, 20), (3, 8), (21, 8))
            if kind == 'folder-add':
                line((9, 14), (15, 14)); line((12, 11), (12, 17))
        elif kind == 'file':
            line((5, 3), (14, 3), (20, 9), (20, 21), (5, 21), (5, 3))
            line((14, 3), (14, 9), (20, 9))
            line((8, 14), (16, 14)); line((8, 17), (14, 17))
        elif kind == 'cancel':
            line((5, 5), (19, 19)); line((19, 5), (5, 19))
        elif kind == 'check':
            line((4, 12), (9, 17), (20, 6))
        elif kind == 'edit':
            line((4, 20), (5, 14), (17, 2), (22, 7), (10, 19), (4, 20))
        else:
            line((12, 4), (12, 20)); line((4, 12), (20, 12))
        painter.drawPath(path)
        painter.restore()


def refresh_button_icon(button):
    kind = button.property('iconKind')
    if not kind:
        return
    dark = button.property('iconSurface') == 'dark'
    primary = button.property('role') == 'primary'
    color = '#ffffff' if dark or primary else '#087f83' if button.property('role') == 'link' else '#20303d'
    disabled = '#8195a0' if dark else '#566d76' if primary else '#85949d'
    button.setIcon(QIcon(LineIconEngine(kind, color, disabled)))


def set_button_icon(button, standard):
    button.setProperty('iconKind', KINDS.get(standard, 'add'))
    refresh_button_icon(button)


def light_icon(kind):
    return QIcon(LineIconEngine(kind, '#20303d', '#85949d'))


class LightFileIconProvider(QFileIconProvider):
    """Avoid light-on-light file decorations supplied by dark desktop themes."""
    def icon(self, target):
        if isinstance(target, QFileInfo):
            return light_icon('folder' if target.isDir() else 'file')
        return light_icon('monitor' if target in (QFileIconProvider.IconType.Computer, QFileIconProvider.IconType.Drive, QFileIconProvider.IconType.Network)
                          else 'folder' if target == QFileIconProvider.IconType.Folder else 'file')


class ContrastIconEngine(QIconEngine):
    """Preserve Qt's dialog icon shapes but give them a legible foreground."""
    def __init__(self, source):
        super().__init__()
        self.source = QIcon(source)

    def clone(self):
        return ContrastIconEngine(self.source)

    def pixmap(self, size, mode, state):
        result = self.source.pixmap(size, mode, state)
        if not result.isNull():
            image = result.toImage()
            shades = [image.pixelColor(x, y).lightness() for x in range(image.width())
                      for y in range(image.height()) if image.pixelColor(x, y).alpha() > 128]
            # Qt's preview icons include opaque white page interiors. Preserve
            # those details instead of turning the entire page into a dark block.
            if shades and min(shades) < 110 and max(shades) > 235:
                foreground = QColor('#85949d' if mode == QIcon.Disabled else '#20303d')
                for x in range(image.width()):
                    for y in range(image.height()):
                        pixel = image.pixelColor(x, y)
                        light = pixel.lightnessF()
                        image.setPixelColor(x, y, QColor(
                            *[round(channel + (255-channel)*light) for channel in
                              (foreground.red(), foreground.green(), foreground.blue())], pixel.alpha()))
                return QPixmap.fromImage(image)
            painter = QPainter(result)
            painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
            painter.fillRect(result.rect(), QColor('#85949d' if mode == QIcon.Disabled else '#20303d'))
            painter.end()
        return result

    def paint(self, painter, rect, mode, state):
        painter.drawPixmap(rect, self.pixmap(rect.size(), mode, state))


def contrast_dialog_icon(button):
    if button.property('iconKind'):
        refresh_button_icon(button)
    elif not button.icon().isNull() and button.property('contrastIconKey') != button.icon().cacheKey():
        button.setIcon(QIcon(ContrastIconEngine(button.icon())))
        button.setProperty('contrastIconKey', button.icon().cacheKey())
