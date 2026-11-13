"""Paginated, vector trend report; shares the configurable spirometry header."""
from datetime import datetime
from itertools import groupby
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor,QFont,QPen
from app.report import SpirometryReportRenderer
from app.history import METRICS,display_value
from app.history_page import TrendChart


class HistoryReportRenderer(SpirometryReportRenderer):
    def render(self,painter,page_rect):
        self.painter=painter;self.page_rect=page_rect
        self.scale=painter.device().logicalDpiX()/72.
        self.left_margin=self._mm(self.payload.get('margin_left_mm',12))
        self.right_margin=self._mm(self.payload.get('margin_right_mm',12))
        self.top_margin=self._mm(self.payload.get('margin_top_mm',6))
        self.bottom_margin=self._mm(self.payload.get('margin_bottom_mm',12))
        self.page_number=1;self.family=painter.font().family()
        painter.save()
        try:
            x,y,width,bottom=self._page_content_rect();self.bottom=bottom-self._u(18)
            y=self._page_heading(x,y,width)
            y=self._table_header(x,y,width)
            layouts=[]
            for index,record in enumerate(self.payload['records']):
                values=self._row_values(record)
                painter.setFont(QFont(self.family,8))
                heights=[painter.boundingRect(QRectF(0,0,w-self._u(8),self._u(500)),Qt.TextWordWrap,value).height()+self._u(8)
                         for w,value in zip(self._widths(width),values)]
                layouts.append((record['session_id'],index,values,max(self._u(24),*heights)))
            # Keep PRE and POST of one visit together at page breaks.
            for _,group in groupby(layouts,key=lambda row:row[0]):
                group=list(group)
                if y+sum(row[3] for row in group)>self.bottom:
                    self._next_page();x,y,width,_=self._page_content_rect()
                    y=self._table_header(x,self._page_heading(x,y,width),width)
                for _,index,values,height in group:
                    self._table_row(x,y,width,height,values,index);y+=height
            y+=self._u(10)
            chart_minimum=self._u(3*84+24)
            if self.bottom-y<chart_minimum:
                self._next_page();x,y,width,_=self._page_content_rect();y=self._page_heading(x,y,width)
            painter.setFont(QFont(self.family,9,QFont.Bold));painter.setPen(QColor('#20303d'))
            painter.drawText(QRectF(x,y,width,self._u(18)),Qt.AlignLeft,'Evolución · '+self.payload['phase_label'])
            y+=self._u(20)
            height=min(self._u(110),(self.bottom-y-self._u(8))/3)
            for key in self.payload['chart_keys']:
                chart=TrendChart(key)
                chart.records=self.payload['plot_records'];chart.phases=set(self.payload['phases'])
                painter.save();painter.translate(x,y)
                factor=width/1000.;painter.scale(factor,factor)
                font=QFont(self.family);font.setPixelSize(12);painter.setFont(font)
                chart.draw_chart(painter,1000,height/factor)
                painter.restore();chart.deleteLater();y+=height
            self._footer()
        finally:painter.restore()

    def _page_heading(self,x,y,width):
        p=self.painter;p.setPen(QColor('#111827'))
        y=self._draw_header(p,x,y,width)+self._u(6)
        p.setFont(QFont(self.family,12,QFont.Bold))
        p.drawText(QRectF(x,y,width,self._u(20)),Qt.AlignLeft,'Tendencia espirométrica')
        y+=self._u(23)
        patient=self.payload['patient']
        name=f"Paciente: {patient['first_name']} {patient['last_name']}"
        p.setFont(QFont(self.family,10,QFont.Bold))
        rect=p.boundingRect(QRectF(x,y,width,self._u(60)),Qt.TextWordWrap,name)
        p.drawText(rect,Qt.TextWordWrap,name);y=rect.bottom()+self._u(4)
        p.setFont(QFont(self.family,9))
        text=f"DNI: {patient['dni'] or '-'}    Nacimiento: {self.payload['birth_date']}    Sexo: {self.payload['sex']}"
        rect=p.boundingRect(QRectF(x,y,width,self._u(50)),Qt.TextWordWrap,text)
        p.drawText(rect,Qt.TextWordWrap,text);y=rect.bottom()+self._u(5)
        p.setFont(QFont(self.family,8))
        stamps=[datetime.fromisoformat(r['created_at']) for r in self.payload['records']]
        period=stamps[0].strftime('%d/%m/%Y')+' - '+stamps[-1].strftime('%d/%m/%Y')
        count=len({r['session_id'] for r in self.payload['records']})
        note=(f"Período: {period} · {count} estudios · {self.payload['phase_label']} · Valores absolutos; referencias originales por estudio.")
        rect=p.boundingRect(QRectF(x,y,width,self._u(60)),Qt.TextWordWrap,note)
        p.drawText(rect,Qt.TextWordWrap,note)
        return rect.bottom()+self._u(10)

    @staticmethod
    def _row_values(record):
        stamp=datetime.fromisoformat(record['created_at'])
        return [stamp.strftime('%d/%m/%Y\n%H:%M:%S'),record['phase'].upper() or '-']+[
            display_value(key,record['values'].get(key)) for key in METRICS]+[record['origin'],record['reference']]

    def _widths(self,width):
        weights=[82,30]+[44]*len(METRICS)+[56,104]
        return [width*value/sum(weights) for value in weights]

    def _table_header(self,x,y,width):
        headers=['Fecha y hora','Fase']+[label+'\n('+unit+')' for label,unit in METRICS.values()]+['Origen','Referencia']
        self._table_row(x,y,width,self._u(28),headers,-1)
        return y+self._u(28)

    def _table_row(self,x,y,width,height,values,index):
        p=self.painter
        p.setFont(QFont(self.family,8,QFont.Bold if index<0 else QFont.Normal))
        p.fillRect(QRectF(x,y,width,height),QColor('#eaf1f4' if index<0 else '#ffffff' if index%2 else '#f7fafb'))
        for column,(cell_width,value) in enumerate(zip(self._widths(width),values)):
            rect=QRectF(x,y,cell_width,height)
            p.setPen(QPen(QColor('#cedbe1'),self._u(.35)));p.drawRect(rect)
            color='#2563eb' if column==1 and value=='PRE' else '#0f8a74' if column==1 and value=='POST' else '#20303d'
            p.setPen(QColor(color))
            p.drawText(rect.adjusted(self._u(4),self._u(3),-self._u(4),-self._u(3)),Qt.AlignVCenter|Qt.AlignHCenter|Qt.TextWordWrap,value)
            x+=cell_width

    def _next_page(self):
        self._footer()
        if not self.painter.device().newPage():raise RuntimeError('No se pudo agregar una página al informe.')
        self.page_number+=1

    def _footer(self):
        x,_,width,bottom=self._page_content_rect();p=self.painter
        p.setFont(QFont(self.family,8));p.setPen(QColor('#617985'))
        text=f"NeumoFlow · Tendencia · Emitido {self.payload['issued_at']} · Página {self.page_number}"
        p.drawText(QRectF(x,bottom-self._u(12),width,self._u(12)),Qt.AlignRight|Qt.AlignVCenter,text)
