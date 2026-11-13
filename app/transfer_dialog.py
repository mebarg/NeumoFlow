"""Folder preview and versioned study export, using the shared light theme."""
from datetime import datetime

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QCheckBox,
    QTextEdit, QFileDialog, QMessageBox)
from app import study_transfer as transfer
from app.ui_theme import apply_theme, file_dialog, role
from app.ui_icons import set_button_icon
from PySide6.QtWidgets import QStyle


class Task(QThread):
    result = Signal(object)
    failure = Signal(str)

    def __init__(self, function, parent):
        super().__init__(parent)
        self.function = function

    def run(self):
        try:
            self.result.emit(self.function())
        except Exception as exc:
            self.failure.emit(str(exc))


class TransferDialog(QDialog):
    def __init__(self, parent=None, exporting=False):
        super().__init__(parent)
        self.exporting = exporting
        self.changed = False
        self.task = None
        self.items = []
        self.setWindowTitle('Exportar estudios' if exporting else 'Importar estudios')
        self.resize(1060, 660)
        apply_theme(self)
        layout = QVBoxLayout(self)
        intro = QLabel('Elegí los estudios que querés guardar en un archivo .espiro. Incluye pacientes, '
                       'resultados, curvas e informes para volver a importarlos en esta aplicación.' if exporting else
                       'Elegí una carpeta con archivos COW de Breeze (6.2 / 6.4.1) o paquetes .espiro. '
                       'Revisá la lista y seleccioná los estudios antes de importar. Se leen los archivos de esa carpeta, sin subcarpetas.')
        intro.setWordWrap(True)
        layout.addWidget(intro)
        tools = QHBoxLayout()
        self.folder_button = QPushButton('Elegir carpeta…')
        set_button_icon(self.folder_button, QStyle.SP_DialogOpenButton)
        self.folder_button.clicked.connect(self.choose_folder)
        if not exporting:
            tools.addWidget(self.folder_button)
        self.location = QLabel('')
        self.location.setWordWrap(True)
        tools.addWidget(self.location, 1)
        self.select_all = QPushButton('Seleccionar todos')
        self.select_none = QPushButton('Quitar selección')
        self.select_all.clicked.connect(lambda: self.select_rows(True))
        self.select_none.clicked.connect(lambda: self.select_rows(False))
        tools.addWidget(self.select_all)
        tools.addWidget(self.select_none)
        layout.addLayout(tools)
        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(['Elegir', 'Paciente', 'DNI / ID', 'Fecha del estudio', 'Maniobras', 'Formato', 'Estado', 'Archivo'])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.verticalHeader().hide()
        self.table.itemSelectionChanged.connect(self.show_details)
        layout.addWidget(self.table, 1)
        self.replace_box = QCheckBox('Reemplazar los estudios duplicados seleccionados (se crea una copia de seguridad)')
        self.replace_box.setChecked(False)
        self.replace_box.toggled.connect(self.replacement_changed)
        if not exporting:
            layout.addWidget(self.replace_box)
        self.status = QLabel('')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.details = QTextEdit()
        self.details.setReadOnly(True)
        self.details.setMaximumHeight(110)
        self.details.setPlaceholderText('Seleccioná una fila para ver los detalles y las observaciones.')
        layout.addWidget(self.details)
        footer = QHBoxLayout()
        self.close_button = QPushButton('Cerrar')
        self.close_button.clicked.connect(self.reject)
        self.action = role(QPushButton('Exportar seleccionados…' if exporting else 'Importar seleccionados'), 'primary')
        self.action.setEnabled(False)
        self.action.clicked.connect(self.execute)
        footer.addStretch()
        footer.addWidget(self.close_button)
        footer.addWidget(self.action)
        layout.addLayout(footer)
        if exporting:
            self.items = transfer.export_candidates()
            self.fill_table()

    def start_task(self, function, callback):
        self.task = Task(function, self)
        for widget in (self.action, self.folder_button, self.select_all, self.select_none,
                       self.replace_box, self.close_button, self.table):
            widget.setEnabled(False)
        self.task.result.connect(callback)
        self.task.failure.connect(self.failed)
        self.task.finished.connect(self.task_finished)
        self.task.start()

    def task_finished(self):
        task, self.task = self.task, None
        task.deleteLater()
        for widget in (self.folder_button, self.select_all, self.select_none, self.replace_box,
                       self.close_button, self.table):
            widget.setEnabled(True)
        self.action.setEnabled(bool(self.items))

    def failed(self, message):
        self.status.setText('No se completó la operación.')
        QMessageBox.warning(self, self.windowTitle(), message)

    def reject(self):
        if self.task is None:
            super().reject()

    def closeEvent(self, event):
        if self.task is not None:
            event.ignore()
        else:
            super().closeEvent(event)

    def choose_folder(self):
        dialog = file_dialog(self, 'Carpeta de estudios para importar', 'Estudios (*.cow *.espiro)')
        dialog.setFileMode(QFileDialog.Directory)
        dialog.setOption(QFileDialog.ShowDirsOnly, True)
        folder = dialog.selectedFiles()[0] if dialog.exec() == QDialog.Accepted else ''
        dialog.deleteLater()
        if folder:
            self.location.setText(folder)
            self.status.setText('Leyendo archivos y comprobando duplicados…')
            self.details.clear()
            self.start_task(lambda: transfer.scan_folder(folder), self.scanned)

    def scanned(self, result):
        self.items, self.errors = result
        self.fill_table()
        self.status.setToolTip('')
        messages = '\n'.join(f'{name}: {error}' for name, error in self.errors)
        self.details.setPlainText(messages)
        if self.errors:
            # Keep errors visible after selecting a row as well.
            self.status.setToolTip(messages)
            self.status.setText(self.status.text()+f' {len(self.errors)} archivos omitidos o con observaciones; detalles debajo.')

    def fill_table(self):
        self.table.setRowCount(len(self.items))
        for i, item in enumerate(self.items):
            if self.exporting:
                values = ['', f"{item['last_name']}, {item['first_name']}", item['dni'] or '',
                          item['created_at'], str(item['maneuver_count']), 'Espirometría', 'Disponible', '']
                duplicate = False
            else:
                values = ['', f"{item.patient['last_name']}, {item.patient['first_name']}", item.patient['dni'] or '',
                          item.session['created_at'], str(len(item.maneuvers)+len(item.respiratory)),
                          'Breeze COW' if item.filename.lower().endswith('.cow') else '.espiro',
                          'Duplicado · se omite' if item.duplicate_id else 'Nuevo', item.filename]
                duplicate = bool(item.duplicate_id)
            for j, value in enumerate(values):
                cell = QTableWidgetItem(value)
                if j == 0:
                    cell.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable | Qt.ItemIsSelectable)
                    cell.setCheckState(Qt.Unchecked if duplicate else Qt.Checked)
                self.table.setItem(i, j, cell)
        duplicates = 0 if self.exporting else sum(bool(s.duplicate_id) for s in self.items)
        self.status.setText(f'{len(self.items)} estudios disponibles.' +
                            (f' {duplicates} duplicados: no se reemplazan salvo que actives la opción y selecciones sus filas.' if duplicates else ''))
        self.action.setEnabled(bool(self.items) and self.task is None)

    def select_rows(self, checked):
        for row in range(self.table.rowCount()):
            self.table.item(row, 0).setCheckState(Qt.Checked if checked else Qt.Unchecked)

    def replacement_changed(self, enabled):
        # No implicit selection of duplicates: replacement needs the option AND the row.
        for i, item in enumerate(self.items):
            if not self.exporting and item.duplicate_id:
                self.table.item(i, 6).setText('Duplicado · reemplazable' if enabled else 'Duplicado · se omite')

    def show_details(self):
        row = self.table.currentRow()
        if self.exporting or not 0 <= row < len(self.items):
            return
        item = self.items[row]
        text = [item.filename, f"{len(item.maneuvers)} FVC, {len(item.respiratory)} SVC/MVV; "
                f"{sum(m['accepted'] for m in item.maneuvers)} incluidas en el sumario original."] + item.warnings
        if item.duplicate_id:
            text.append('Reemplazar sustituye las maniobras y el informe de este estudio. La ficha personal existente se conserva.')
        if getattr(self, 'errors', []):
            text += ['', 'Archivos omitidos / observaciones:'] + [f'{name}: {message}' for name, message in self.errors]
        self.details.setPlainText('\n'.join(text))

    def execute(self):
        selected = [item for i, item in enumerate(self.items) if self.table.item(i, 0).checkState() == Qt.Checked]
        if not selected:
            QMessageBox.information(self, self.windowTitle(), 'Seleccioná al menos un estudio.')
            return
        if self.exporting:
            dialog = file_dialog(self, 'Exportar estudios', 'Estudios Espirometría (*.espiro)',
                                 'estudios_'+datetime.now().strftime('%Y%m%d_%H%M')+'.espiro', save=True)
            path = dialog.selectedFiles()[0] if dialog.exec() == QDialog.Accepted else ''
            dialog.deleteLater()
            if not path:
                return
            if not path.lower().endswith('.espiro'):
                path += '.espiro'
            self.status.setText('Exportando y verificando el paquete…')
            self.start_task(lambda: (transfer.export_studies(path, [s['id'] for s in selected]), path), self.exported)
        else:
            replace = self.replace_box.isChecked()
            self.status.setText('Importando estudios…')
            self.start_task(lambda: transfer.import_studies(selected, replace=replace), self.imported)

    def exported(self, result):
        count, path = result
        self.status.setText(f'{count} estudios exportados y verificados.')
        self.details.setPlainText('Archivo guardado:\n'+path)

    def imported(self, result):
        self.changed |= bool(result['imported'])
        self.status.setText(f"Importados: {result['imported']}. Reemplazados: {result['replaced']}. Omitidos: {result['skipped']}.")
        self.details.setPlainText('Copia de seguridad: '+result['backup'] if result['backup'] else 'Importación terminada. Los archivos originales se conservan.')
        self.action.setText('Importación terminada')
        # Recheck the table without losing the outcome or selecting new duplicates.
        with transfer.db.connect() as conn:
            for i, item in enumerate(self.items):
                item.duplicate_id = transfer._duplicate(conn, item)
                if item.duplicate_id:
                    self.table.item(i, 0).setCheckState(Qt.Unchecked)
                    self.table.item(i, 6).setText('Ya importado · duplicado')
