"""Explicit, saved operator decisions for suspected FVC artifacts."""
from copy import deepcopy
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QLabel, QTableWidget, QTableWidgetItem,
                               QComboBox, QDialogButtonBox, QHeaderView)
from app.fvc_quality import assessment, apply_decisions, event_label, STATES


class QualityReviewDialog(QDialog):
    def __init__(self, params, parent=None):
        super().__init__(parent)
        self.params = deepcopy(params)
        self.setWindowTitle('Revisión de calidad de la maniobra')
        self.resize(670, 400)
        layout = QVBoxLayout(self)
        note = QLabel('Detecciones orientativas, pendientes de revisión visual. Confirmá o descartá cada sospecha. '
                      '«Sin alertas automáticas» no acredita aceptabilidad ATS/ERS. Los valores medidos no se modifican.')
        note.setWordWrap(True)
        layout.addWidget(note)
        self.evaluation = QLabel()
        self.evaluation.setWordWrap(True)
        layout.addWidget(self.evaluation)
        self.table = QTableWidget(len(params.get('quality_events', [])), 3)
        self.table.setHorizontalHeaderLabels(['Evento', 'Intervalo desde T0', 'Revisión del operador'])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(44)
        self.selectors = {}
        for row, event in enumerate(params.get('quality_events', [])):
            self.table.setItem(row, 0, QTableWidgetItem(event_label({**event, 'decision':'pending'})))
            self.table.setItem(row, 1, QTableWidgetItem(f"{event['start_t0']:.2f}–{event['end_t0']:.2f} s"))
            choice = QComboBox()
            choice.setProperty('referenceSelector', True)
            for text, value in [('Pendiente', 'pending'), ('Confirmar evento', 'confirmed'), ('Descartar sospecha', 'dismissed')]:
                choice.addItem(text, value)
            choice.setCurrentIndex(choice.findData(event.get('decision', 'pending')))
            self.selectors[event['id']] = choice
            choice.currentIndexChanged.connect(self.update_evaluation)
            self.table.setCellWidget(row, 2, choice)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self.table)
        if not self.selectors:
            layout.addWidget(QLabel('No se detectaron sospechas de tos, cierre glótico o interrupción en esta curva.'))
        self.update_evaluation()
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText('Guardar revisión')
        buttons.button(QDialogButtonBox.Cancel).setText('Cancelar')
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def decisions(self):
        return {key: choice.currentData() for key, choice in self.selectors.items()}

    def update_evaluation(self):
        params = apply_decisions(self.params, self.decisions(), 'preview')
        states = assessment(params)
        self.evaluation.setText('\n'.join(key.upper()+': '+STATES[states[key]['state']] +
            (' — '+'; '.join(states[key]['reasons']) if states[key]['reasons'] else '') for key in ('fev1', 'fvc')))
