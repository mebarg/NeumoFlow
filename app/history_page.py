"""Patient trends: independent dates, PRE/POST series, gaps and visit navigation."""
import math
from datetime import datetime
from PySide6.QtCore import Qt, QRectF, QPointF, Signal, QSignalBlocker
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QLabel,QTableWidget,QTableWidgetItem,
    QHeaderView,QAbstractItemView,QCheckBox,QComboBox,QPushButton,QSplitter,QToolTip)
from app.history import METRICS, display_value, patient_history

COLORS={'pre':'#2563eb','post':'#0f8a74'}


class TrendChart(QWidget):
    selected=Signal(int,str)

    def __init__(self,key,parent=None):
        super().__init__(parent)
        self.key=key;self.records=[];self.phases={'pre','post'};self.selection=None;self.targets=[];self.date_labels=[]
        self.setMinimumHeight(90);self.setMouseTracking(True)

    def paintEvent(self,event):
        painter=QPainter(self)
        self.draw_chart(painter,self.width(),self.height())

    def draw_chart(self,painter,width,height):
        """Draw the same chart on screen or directly onto a PDF/printer painter."""
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(QRectF(0,0,width,height),QColor('white'))
        title,unit=METRICS[self.key]
        painter.setPen(QColor('#20303d'));painter.drawText(10,17,title+' · '+unit)
        area=QRectF(66,29,max(1,width-100),max(1,height-54))
        self.targets=[];self.date_labels=[]
        points=[r for r in self.records if r['phase'] in self.phases and r['values'].get(self.key) is not None]
        if not points:
            painter.setPen(QColor('#617985'))
            painter.drawText(area,Qt.AlignCenter,'Sin valores incluidos de '+title)
            return
        dates=[datetime.fromisoformat(r['created_at']).timestamp() for r in self.records]
        low,high=min(dates),max(dates);span=high-low
        pad=max(span*.04,3600.);low-=pad;high+=pad
        values=[r['values'][self.key]*(100 if self.key=='fev1_fvc' else 1) for r in points]
        vmax=max(values);vmin=min(0.,min(values));vmax=max(vmax*1.12,vmin+1.)
        def position(record):
            value=record['values'][self.key]*(100 if self.key=='fev1_fvc' else 1)
            stamp=datetime.fromisoformat(record['created_at']).timestamp()
            return QPointF(area.left()+(stamp-low)/(high-low)*area.width(),area.bottom()-(value-vmin)/(vmax-vmin)*area.height())
        for fraction in (0.,.5,1.):
            y=area.bottom()-area.height()*fraction
            painter.setPen(QPen(QColor('#e3ebf0'),1));painter.drawLine(QPointF(area.left(),y),QPointF(area.right(),y))
            painter.setPen(QColor('#617985'))
            painter.drawText(QRectF(0,y-8,58,16),Qt.AlignRight|Qt.AlignVCenter,f'{vmin+(vmax-vmin)*fraction:.1f}')
        # Labels come only from actual plotted visits, never synthetic midpoints.
        ticks=[]
        for stamp in sorted({datetime.fromisoformat(r['created_at']).timestamp() for r in points}):
            x=area.left()+(stamp-low)/(high-low)*area.width()
            date=datetime.fromtimestamp(stamp)
            label=date.strftime('%d/%m/%y') if span>=172800 else date.strftime('%d/%m %H:%M')
            ticks.append((stamp,x,label))
        chosen=[ticks[0]]
        if ticks[-1][1]-ticks[0][1]>=110:chosen.append(ticks[-1])
        for tick in ticks[1:-1]:
            if all(abs(tick[1]-other[1])>=110 for other in chosen):chosen.append(tick)
        for stamp,x,label in sorted(chosen):
            self.date_labels.append((stamp,label))
            painter.setPen(QColor('#617985'))
            painter.drawText(QRectF(x-48,area.bottom()+4,96,20),Qt.AlignCenter,label)
        # Empty visits and missing values break each phase's connecting line.
        for phase in ('pre','post'):
            if phase not in self.phases:continue
            color=QColor(COLORS[phase]);path=QPainterPath();connected=False
            visits={r['session_id']:r for r in self.records if r['phase']==phase}
            seen=set()
            for record in self.records:
                sid=record['session_id']
                if sid in seen:continue
                seen.add(sid);record=visits.get(sid)
                if record is None or record['values'].get(self.key) is None:
                    connected=False;continue
                pos=position(record)
                if connected:path.lineTo(pos)
                else:path.moveTo(pos)
                connected=True;self.targets.append((pos,record))
            painter.setPen(QPen(color,1.7));painter.drawPath(path)
        for pos,record in self.targets:
            color=QColor(COLORS[record['phase']]);painter.setPen(QPen(color,1.7));painter.setBrush(QColor('white'))
            if record['phase']=='pre':painter.drawEllipse(pos,3.5,3.5)
            else:painter.drawRect(QRectF(pos.x()-3.5,pos.y()-3.5,7,7))
            if self.selection and self.selection==(record['session_id'],record['phase']):
                painter.setBrush(Qt.NoBrush);painter.setPen(QPen(QColor('#20303d'),1));painter.drawEllipse(pos,6.5,6.5)

    def _hit(self,pos):
        candidates=[((point.x()-pos.x())**2+(point.y()-pos.y())**2,record) for point,record in self.targets]
        distance,record=min(candidates,key=lambda item:item[0]) if candidates else (math.inf,None)
        return record if distance<=100 else None

    def mouseMoveEvent(self,event):
        record=self._hit(event.position())
        if record:
            label,unit=METRICS[self.key]
            text=(datetime.fromisoformat(record['created_at']).strftime('%d/%m/%Y %H:%M:%S')+
                  f" · Estudio {record['session_id']} · {record['phase'].upper()}\n"+
                  f"{label}: {display_value(self.key,record['values'][self.key])} {unit}\n"+
                  record['origin']+' · Referencia: '+record['reference'])
            QToolTip.showText(event.globalPosition().toPoint(),text,self)
            self.setCursor(Qt.PointingHandCursor)
        else:QToolTip.hideText();self.unsetCursor()

    def mousePressEvent(self,event):
        record=self._hit(event.position())
        if event.button()==Qt.LeftButton and record:self.selected.emit(record['session_id'],record['phase'])


class HistoryPage(QWidget):
    open_study=Signal(int)

    def __init__(self,window):
        super().__init__();self.records=[];self.selected_studies=set();self.patient_id=None
        layout=QVBoxLayout(self);layout.setContentsMargins(0,8,0,0);layout.setSpacing(8)
        controls=QHBoxLayout()
        self.pre=QCheckBox('PRE · azul');self.post=QCheckBox('POST · verde')
        for checkbox in (self.pre,self.post):checkbox.setChecked(True);controls.addWidget(checkbox);checkbox.toggled.connect(self.refresh)
        controls.addStretch()
        self.print_button=QPushButton('Imprimir')
        self.print_button.clicked.connect(window.preview_history_report)
        self.pdf_button=QPushButton('Guardar PDF')
        self.pdf_button.setProperty('role','primary')
        self.pdf_button.clicked.connect(window.save_history_pdf)
        controls.addWidget(self.print_button);controls.addWidget(self.pdf_button)
        self.open_button=QPushButton('Abrir estudio seleccionado');self.open_button.clicked.connect(self.open_selected)
        controls.addWidget(self.open_button);layout.addLayout(controls)
        self.note=QLabel('Valores absolutos de maniobras incluidas, iguales al sumario. Cada estudio conserva sus referencias. Las ausencias cortan las líneas; no se grafican como cero.')
        self.note.setWordWrap(True);self.note.setProperty('role','muted');layout.addWidget(self.note)
        splitter=QSplitter(Qt.Vertical)
        self.table=QTableWidget(0,5+len(METRICS))
        self.table.setHorizontalHeaderLabels(['Graficar','Fecha y hora','Fase']+[label+' ('+unit+')' for label,unit in METRICS.values()]+['Origen','Referencia'])
        window._set_light_result_palette(self.table)
        self.table.verticalHeader().hide();self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows);self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setMinimumHeight(85);self.table.itemSelectionChanged.connect(self.selection_changed)
        self.table.itemChanged.connect(self.plot_changed)
        self.table.doubleClicked.connect(lambda index:self.open_selected() if index.column()!=0 else None);splitter.addWidget(self.table)
        graphs=QWidget();gl=QVBoxLayout(graphs);gl.setContentsMargins(0,0,0,0);gl.setSpacing(6)
        self.charts=[];self.selectors=[]
        for key in ('fev1','fvc','pef'):
            combo=QComboBox();combo.setProperty('referenceSelector',True)
            for metric,(label,unit) in METRICS.items():combo.addItem(label+' · '+unit,metric)
            combo.setCurrentIndex(combo.findData(key));self.selectors.append(combo)
            chart=TrendChart(key);chart.selected.connect(self.select_point);self.charts.append(chart)
            combo.currentIndexChanged.connect(lambda _,c=combo,g=chart:self.change_metric(g,c.currentData()))
            row=QHBoxLayout();combo.setFixedWidth(125);row.addWidget(combo);row.addWidget(chart,1);gl.addLayout(row,1)
        self.graph_scroll=window._scroll_content(graphs)
        splitter.addWidget(self.graph_scroll);splitter.setSizes([180,380]);splitter.setCollapsible(0,False);splitter.setCollapsible(1,False)
        layout.addWidget(splitter,1)
        self.status=QLabel();self.status.setWordWrap(True);self.status.setProperty('role','muted');layout.addWidget(self.status)

    def load(self,patient_id):
        self.patient_id=patient_id
        self.records=patient_history(patient_id)
        self.selected_studies={record['session_id'] for record in self.records}
        with QSignalBlocker(self.table):
            self.table.clearSelection();self.table.setCurrentCell(-1,-1);self.table.setRowCount(len(self.records))
            for index,record in enumerate(self.records):
                values=['',datetime.fromisoformat(record['created_at']).strftime('%d/%m/%Y %H:%M:%S'),record['phase'].upper() or '–']
                values += [display_value(key,record['values'][key]) for key in METRICS]
                values += [record['origin'],record['reference']]
                for column,value in enumerate(values):
                    item=QTableWidgetItem(value);item.setData(Qt.UserRole,(record['session_id'],record['phase']))
                    if column==0:
                        item.setFlags(item.flags()|Qt.ItemIsUserCheckable)
                        item.setCheckState(Qt.Checked)
                        item.setToolTip('Mostrar este estudio en los gráficos (PRE y POST).')
                    else:
                        item.setToolTip(f"Estudio {record['session_id']} · {record['included_count']} maniobras incluidas\n"+
                                        (record['reference_note'] or record['reference']))
                    if column not in (1,len(values)-2,len(values)-1):item.setTextAlignment(Qt.AlignCenter)
                    self.table.setItem(index,column,item)
        self.refresh()

    def plot_changed(self,item):
        if item.column()!=0:return
        sid=item.data(Qt.UserRole)[0]
        if item.checkState()==Qt.Checked:self.selected_studies.add(sid)
        else:self.selected_studies.discard(sid)
        # PRE and POST rows represent the same study selection.
        with QSignalBlocker(self.table):
            for index,record in enumerate(self.records):
                if record['session_id']==sid:self.table.item(index,0).setCheckState(item.checkState())
        self.refresh()

    def refresh(self,*_):
        phases={phase for phase,check in (('pre',self.pre),('post',self.post)) if check.isChecked()}
        for index,record in enumerate(self.records):self.table.setRowHidden(index,bool(record['phase']) and record['phase'] not in phases)
        plotted=[record for record in self.records if record['session_id'] in self.selected_studies]
        for chart in self.charts:chart.records=plotted;chart.phases=phases;chart.update()
        self.status.setText(f"{len(self.selected_studies)} de {len({r['session_id'] for r in self.records})} estudios seleccionados · Doble clic en una fila para abrir el estudio." if self.records else 'Este paciente todavía no tiene estudios.')
        can_print=bool(self.report_records())
        self.print_button.setEnabled(can_print);self.pdf_button.setEnabled(can_print)
        self.selection_changed()

    def report_records(self):
        phases={phase for phase,check in (('pre',self.pre),('post',self.post)) if check.isChecked()}
        return [record for record in self.records if record['session_id'] in self.selected_studies and
                (not record['phase'] or record['phase'] in phases)]

    @staticmethod
    def change_metric(chart,key):chart.key=key;chart.update()

    def selection_changed(self):
        row=self.table.currentRow()
        record=self.records[row] if 0<=row<len(self.records) and not self.table.isRowHidden(row) else None
        self.open_button.setEnabled(record is not None)
        for chart in self.charts:
            chart.selection=(record['session_id'],record['phase']) if record else None;chart.update()

    def select_point(self,sid,phase):
        for index,record in enumerate(self.records):
            if record['session_id']==sid and record['phase']==phase:
                self.table.selectRow(index);self.table.scrollToItem(self.table.item(index,0));return

    def open_selected(self):
        row=self.table.currentRow()
        if 0<=row<len(self.records) and not self.table.isRowHidden(row):self.open_study.emit(self.records[row]['session_id'])
