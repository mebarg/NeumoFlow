"""Guided SVC and MVV collection using the study's existing USB stream."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QLabel,QComboBox,
                              QPushButton,QTableWidget,QTableWidgetItem,QHeaderView,QAbstractItemView,QMessageBox,QApplication)
from app import db
from app.charts import CurveWidget, CURVE_COLORS
from app.ui_theme import role
from app.respiratory_measurements import tidal_baseline


class RespiratoryPage(QWidget):
    def __init__(self, window, kind):
        super().__init__()
        self.window,self.kind=window,kind
        self.loading=False
        self.live_curve=[]
        self.marked=False
        self.mark_time=None
        self.baseline_cued=False
        self.plateau_cued=False
        self.records=[]
        layout=QVBoxLayout(self)
        self.patient_label=role(QLabel(), 'pageTitle')
        self.patient_data=role(QLabel(), 'muted')
        layout.addLayout(window._patient_heading(self.patient_label,self.patient_data))
        controls=QHBoxLayout()
        controls.addWidget(QLabel('Fase del estudio'))
        self.phase=QComboBox();self.phase.addItem('PRE','pre');self.phase.addItem('POST','post')
        controls.addWidget(self.phase)
        self.phase.setProperty("referenceSelector",True)
        self.phase.currentIndexChanged.connect(lambda _:window.set_study_phase(self.phase.currentData()))
        self.option=QComboBox()
        self.option.setProperty("referenceSelector",True)
        if kind=='svc':
            self.option.addItem('Capacidad vital espiratoria (EVC)', 'evc')
            self.option.addItem('Capacidad vital inspiratoria (IVC)', 'ivc')
        else:
            self.option.addItem('Intervalo de 12 segundos',12);self.option.addItem('Intervalo de 15 segundos',15)
        controls.addWidget(self.option);controls.addStretch()
        self.status=role(QLabel('Preparando conexión…'),'muted');controls.addWidget(self.status)
        layout.addLayout(controls)
        self.guide=QLabel(('Respiración tranquila → marcar comienzo → inspiración y espiración máximas lentas → finalizar. '
                          'IC y ERV requieren al menos tres respiraciones con nivel espiratorio estable.') if kind=='svc' else
                         ('Respiración preparatoria → comenzar intervalo → respirar profunda y rápidamente hasta la parada automática. '
                          'Finalizá antes con Espacio si es necesario. MVV puede causar mareo o fatiga; requiere supervisión.'))
        self.guide.setWordWrap(True);layout.addWidget(self.guide)
        self.option.currentIndexChanged.connect(self.update_guide)
        self.update_guide()
        self.chart=CurveWidget('volume_time');self.chart.configure_study_axes(6.,30. if kind=='svc' else 20.)
        self.table=QTableWidget(0,12 if kind=='svc' else 11)
        window._set_light_result_palette(self.table)
        self.table.setHorizontalHeaderLabels(['Hora','Fase','Incluir','SVC (L)','IC (L)','ERV (L)','VT (L)','Duración (s)','Predicho','% teo','z','Revisión'] if kind=='svc' else
                                            ['Hora','Fase','Incluir','MVV (L/min)','VT (L)','FR (min⁻¹)','Intervalo (s)','Predicho','% teo','z','Revisión'])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(self.table.columnCount()-1,QHeaderView.Stretch)
        self.table.verticalHeader().hide();self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.itemChanged.connect(self.include_changed)
        self.table.itemSelectionChanged.connect(self.show_curves)
        layout.addWidget(self.table,1)
        layout.addWidget(window._chart_panel('Volumen / tiempo',self.chart,'Volumen en L · tiempo en s'),1)
        self.repeatability=role(QLabel(),'muted');self.repeatability.setWordWrap(True);layout.addWidget(self.repeatability)
        buttons=QHBoxLayout()
        self.start=role(QPushButton('Iniciar maniobra'),'primary');self.start.clicked.connect(self.toggle)
        self.mark=QPushButton('Comenzar esfuerzo lento' if kind=='svc' else 'Comenzar intervalo MVV');self.mark.clicked.connect(self.mark_effort)
        self.zero=QPushButton('Flujo cero');self.zero.clicked.connect(window.repeat_zero)
        self.remove=QPushButton('Borrar seleccionada');self.remove.clicked.connect(self.delete_selected)
        buttons.addWidget(self.start);buttons.addWidget(QLabel('Espacio'));buttons.addWidget(self.mark);buttons.addWidget(self.zero)
        buttons.addStretch();buttons.addWidget(self.remove)
        show=QPushButton('Ver sumario');show.clicked.connect(window.show_summary);buttons.addWidget(show)
        self.summary_button=show
        layout.addLayout(buttons)
        self.shortcut=QShortcut(QKeySequence(Qt.Key_Space),self);self.shortcut.setAutoRepeat(False)
        self.shortcut.activated.connect(lambda:self.toggle() if self.start.isEnabled() else None)
        self.sync()

    def update_guide(self,*_):
        if self.kind!='svc':return
        effort=('inspirar al máximo y espirar lenta y completamente' if self.option.currentData()=='evc' else
                'espirar completamente e inspirar lenta y completamente')
        self.guide.setText('Respiración tranquila → marcar comienzo → '+effort+' → volver a respirar normalmente → finalizar con Espacio. '
                           'IC y ERV requieren nivel espiratorio estable.')

    def sync(self):
        w=self.window
        active=w.capture_active and getattr(w,'_capture_page',None) is self
        self.start.setText('Finalizar maniobra' if active else 'Iniciar maniobra')
        self.start.setEnabled(active or (w.device_ready and not w.capture_active))
        self.mark.setEnabled(active and not self.marked)
        self.zero.setEnabled(not w.capture_active and (w.device_ready or w.worker is None))
        self.phase.setEnabled(not w.capture_active);self.option.setEnabled(not w.capture_active)
        self.remove.setEnabled(not w.capture_active);self.summary_button.setEnabled(not w.capture_active)
        self.shortcut.setEnabled(w.stack.currentWidget() is self if hasattr(w,'stack') else False)

    def toggle(self):
        if self.window.capture_active:
            if self.window._capture_page is self:
                self.window.worker.stop();self.start.setEnabled(False)
                self.status.setText('Finalizando…')
        else:
            self.window.start_additional_capture(self)

    def mark_effort(self):
        if self.window._capture_page is self and self.window.capture_active and not self.marked:
            self.window.worker.mark_effort();self.marked=True;self.mark.setEnabled(False)
            self.status.setText('Esfuerzo lento en curso' if self.kind=='svc' else 'Intervalo MVV en curso')

    def progress(self,curve):
        self.live_curve=curve;self.chart.set_curve(curve)
        elapsed=curve[-1][0] if curve else 0.
        if not self.marked and self.kind=='svc':
            baseline=tidal_baseline(curve)
            if baseline["baseline_stable"] and not self.baseline_cued:
                QApplication.beep();self.baseline_cued=True
            self.status.setText(f'{elapsed:.1f} s · {baseline["tidal_breaths"]} respiraciones · '+
                                ('nivel estable, podés comenzar' if baseline['baseline_stable'] else 'respiración tranquila'))
        elif self.kind=='mvv' and self.mark_time is not None:
            remaining=max(0.,self.option.currentData()-(elapsed-self.mark_time))
            self.status.setText(f'Intervalo MVV · faltan {remaining:.1f} s')
        else:
            self.status.setText(f'{elapsed:.1f} s · '+('esfuerzo marcado' if self.marked else 'preparación'))
            if self.kind=='svc' and self.mark_time is not None and not self.plateau_cued:
                from app.respiratory_measurements import analyze_curve
                result=analyze_curve(curve,'svc',self.mark_time,self.option.currentData())
                if result.get('plateau'):
                    QApplication.beep();QApplication.beep();self.plateau_cued=True
                    self.status.setText('Meseta detectada · volver a respiración tranquila y finalizar')

    def load(self):
        w=self.window
        if w.current_session_id is None:return
        patient=db.get_patient(w.current_patient_id)
        self.patient_label.setText(f'{patient["first_name"]} {patient["last_name"]}')
        self.patient_data.setText(f'DNI: {patient["dni"] or "–"} · {self.kind.upper()} · Estudio {w.current_session_id}')
        self.records=db.list_respiratory_measurements(w.current_session_id,self.kind)
        from app.reference_policy import EQUATIONS
        from app.reference_values import respiratory_references
        session=db.get_session(w.current_session_id)
        self.loading=True
        self.table.setRowCount(len(self.records))
        def fmt(value):return '–' if value is None else f'{value:.2f}'
        for row,record in enumerate(self.records):
            r=record['result']
            values=[record['created_at'][11:19],record['phase'].upper(),'']
            if self.kind=='svc':values += [fmt(r.get(k)) for k in ('svc','ic','erv','vt','effort_duration')]
            else:values += [fmt(r.get(k)) for k in ('mvv','vt','frequency','interval_seconds')]
            refs=respiratory_references(patient,session,r)
            ref=refs.get(self.kind) or {}
            values += [fmt(ref.get(k)) for k in ('predicted','percent','zscore')]
            values += [(r.get('direction','').upper()+' · ' if self.kind=='svc' else '') + ('; '.join(r.get('warnings',[])) or ('Incluida por el operador' if record['included'] else 'Revisión del operador pendiente'))]
            for col,value in enumerate(values):
                item=QTableWidgetItem(value);item.setData(Qt.UserRole,record['id'])
                if col==2:
                    item.setFlags(item.flags()|Qt.ItemIsUserCheckable)
                    item.setCheckState(Qt.Checked if record['included'] else Qt.Unchecked)
                if self.kind=='mvv' and col==3 and r.get('mvv_estimate') is not None and r.get('mvv') is None:
                    item.setToolTip(f"Estimación provisional: {r['mvv_estimate']:.2f} L/min; intervalo incompleto, no se informa como MVV.")
                if col in (3,4,5):
                    metric=self.kind if col==3 else ('ic' if col==4 else 'erv') if self.kind=='svc' else None
                    detail=refs.get(metric) or {}
                    if detail:
                        item.setToolTip(EQUATIONS[detail['equation']]+f". Predicho: {fmt(detail.get('predicted'))}; %: {fmt(detail.get('percent'))}; z: {fmt(detail.get('zscore'))}. "+detail.get('note',''))
                self.table.setItem(row,col,item)
        self.loading=False
        self.show_curves();self.update_repeatability();self.sync()

    def include_changed(self,item):
        if self.loading or item.column()!=2:return
        record=next(r for r in self.records if r['id']==item.data(Qt.UserRole))
        if item.checkState()==Qt.Checked and record['result'].get(self.kind) is None:
            QMessageBox.information(self,'Medición incompleta','Esta captura no tiene un resultado válido para incluir en el sumario.')
            self.load();return
        db.include_respiratory_measurement(item.data(Qt.UserRole),item.checkState()==Qt.Checked)
        self.load();self.window.refresh_summary_page()

    def show_curves(self):
        row=self.table.currentRow()
        records=self.records if row<0 or row>=len(self.records) else [self.records[row]]
        self.chart.set_curves([r['result'].get('acq_curve',[]) for r in records])

    def update_repeatability(self):
        lines=[]
        for phase in ('pre','post'):
            key='svc' if self.kind=='svc' else 'mvv'
            values=sorted((r['result'][key] for r in self.records if r['phase']==phase and r['included'] and r['result'].get(key) is not None),reverse=True)
            text=f'{phase.upper()}: {len(values)} incluidas (mínimo '+('3)' if self.kind=='svc' else '2)')
            if len(values)>=2:
                delta=values[0]-values[1]
                if self.kind=='svc':
                    from app.reference_values import age_years
                    from datetime import datetime
                    patient=db.get_patient(self.window.current_patient_id);session=db.get_session(self.window.current_session_id)
                    age=age_years(patient['birth_date'],datetime.fromisoformat(session['created_at']).date())
                    limit=min(.100 if age is not None and age<=6 else .150,.1*values[0]) if age is not None else None
                    text+=f' · diferencia {delta:.3f} L'+(f' · límite {limit:.3f} L' if limit is not None else ' · revisar edad')
                else:text+=f' · diferencia {delta/values[0]*100:.1f}%'
            lines.append(text)
        self.repeatability.setText(' | '.join(lines)+' · Incluir exige revisar curvas y esfuerzo; no certifica calidad ATS/ERS.')

    def delete_selected(self):
        row=self.table.currentRow()
        if row<0:return
        if QMessageBox.question(self,'Borrar medición','¿Borrar esta medición y su curva?',QMessageBox.Yes|QMessageBox.No,QMessageBox.No)!=QMessageBox.Yes:return
        db.delete_respiratory_measurement(self.records[row]['id']);self.load();self.window.refresh_summary_page()
