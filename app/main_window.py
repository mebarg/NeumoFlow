import json
import math
import time
from app.breeze_references import REFERENCE_NOTE
from app.reference_policy import (FVC_PARAMETERS, PARAMETERS, EQUATIONS, SUPPORTED, RECOMMENDED, LEGACY, SETTING,
                                  configured_selection, reference_label, reference_description)
from app.reference_values import respiratory_references, respiratory_predicted
from app.fvc_display import volume_time_curve
from app.fvc_quality import (processing as quality_processing, quality_text, metric_eligible, annotate as annotate_quality, plot_regions, assessment as quality_assessment, STATES as QUALITY_STATES)
from datetime import datetime

from PySide6.QtCore import QMarginsF, QRectF, QThread, Qt, QTimer, QSignalBlocker
from PySide6.QtGui import QColor, QFont, QIcon, QImage, QPixmap, QKeySequence, QPageLayout, QPainter, QPageSize, QPalette, QPdfWriter, QShortcut, QTextBlockFormat, QTextCharFormat, QTextCursor
from PySide6.QtPrintSupport import QPrintPreviewDialog, QPrinter
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QButtonGroup,
    QComboBox,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QStyle,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QSpinBox,
    QSplitter,
    QScrollArea,
    QSizePolicy,
    QGridLayout,
    QVBoxLayout,
    QWidget,
)

from app import db
from app.transfer_dialog import TransferDialog
from app.charts import CURVE_COLORS, CurveWidget, ZScoreWidget
from app.reference_values import ETHNICITY_LABELS, gli2012_for_maneuver, gli2012_predicted
from app.report import SpirometryReportRenderer
from app import spirometry
from app.workers import CalibrationSessionWorker, StudySessionWorker
from app.interpretation import generate_report
from app.ui_icons import set_button_icon, refresh_button_icon
from app.branding import APP_NAME, app_icon
from app.ui_theme import PhaseSelector, StatusLabel, PhaseTableDelegate, apply_theme, role, repolish, file_dialog, install_dialog_theme


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME + " · CPFS/D")
        self.setWindowIcon(app_icon())
        apply_theme(self)
        install_dialog_theme(self)

        self.current_patient_id = None
        self.editing_patient_id = None
        self.current_session_id = None
        self.current_samples = None
        self.current_params = None
        self.study_curves = []
        self.study_curve_colors = []
        self.maneuver_curves = {}
        self.maneuver_volume_time_curves = {}
        self.study_volume_time_curves = []
        self.study_volume_time_colors = []
        self.maneuver_selected = {}
        self.maneuver_phase = {}
        self.updating_maneuver_table = False
        self.predicted_values = None
        self.current_phase = "pre"
        self._calibration_notice_key = None
        self.thread = None
        self.worker = None
        self.device_ready = False
        self.capture_active = False
        self._capture_page = None
        self._device_requested = False
        self._device_study_id = None
        self._pending_calibration_start = False
        self.maneuver_started_at = None
        self.calibration_thread = None
        self.calibration_worker = None
        self.calibration_strokes = []
        self.live_calibration_curve = []
        self._last_quality_ready = {}

        db.init_db()
        self._build_ui()
        self.stack.currentChanged.connect(self.study_screen_changed)
        self.stack.currentChanged.connect(self.update_navigation)
        self.refresh_patients()
        self.show_patients()
        available = self.screen().availableGeometry()
        self.resize(min(1280, available.width() - 24), min(840, available.height() - 48))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not hasattr(self, 'mvv_page'):
            return
        chart_height = 140 if self.height() < 760 else 180
        for chart in (self.flow_volume_chart, self.volume_time_chart,
                      self.svc_page.chart, self.mvv_page.chart):
            chart.setMinimumHeight(chart_height)

    def _build_ui(self):
        root = QWidget()
        root.setObjectName("appRoot")
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.sidebar = QFrame()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setFixedWidth(168)
        navigation = QVBoxLayout(self.sidebar)
        navigation.setContentsMargins(14, 26, 14, 20)
        navigation.setSpacing(8)
        brand_row = QHBoxLayout()
        brand_row.setSpacing(8)
        brand_logo = QLabel()
        brand_logo.setObjectName("brandLogo")
        brand_logo.setFixedSize(36, 36)
        brand_logo.setPixmap(self.windowIcon().pixmap(36, 36))
        brand_logo.setAccessibleName("Logo de NeumoFlow")
        brand_row.addWidget(brand_logo)
        brand_text = QVBoxLayout()
        brand_text.setSpacing(3)
        brand = QLabel(APP_NAME)
        brand.setObjectName("brand")
        brand_text.addWidget(brand)
        brand_detail = QLabel("CPFS / D")
        brand_detail.setObjectName("brandDetail")
        brand_text.addWidget(brand_detail)
        brand_row.addLayout(brand_text)
        navigation.addLayout(brand_row)
        navigation.addSpacing(24)
        self.new_patient_button = self._make_button("Nuevo paciente", QStyle.SP_FileIcon)
        self.new_patient_button.setObjectName("newPatient")
        self.patients_button = self._make_button("Pacientes", QStyle.SP_DirHomeIcon)
        self.study_button = self._make_button("Estudio", QStyle.SP_MediaPlay)
        self.calibration_button = self._make_button("Calibración", QStyle.SP_ComputerIcon)
        self.settings_button = self._make_button("Configuración", QStyle.SP_FileDialogDetailedView)
        self.new_patient_button.setProperty("iconSurface", "dark")
        refresh_button_icon(self.new_patient_button)
        navigation.addWidget(self.new_patient_button)
        navigation.addSpacing(12)
        self.navigation_group = QButtonGroup(self)
        for button in (self.patients_button, self.study_button, self.calibration_button, self.settings_button):
            button.setProperty("iconSurface", "dark")
            refresh_button_icon(button)
            button.setCheckable(True)
            self.navigation_group.addButton(button)
            navigation.addWidget(button)
        self.study_button.setEnabled(False)
        navigation.addStretch()
        device_title = QLabel("CPFS/D USB")
        navigation.addWidget(device_title)
        self.device_status_label = QLabel("Sin conexión activa")
        self.device_status_label.setObjectName("deviceStatus")
        self.device_status_label.setWordWrap(True)
        navigation.addWidget(self.device_status_label)
        layout.addWidget(self.sidebar)

        workspace = QWidget()
        workspace.setObjectName("workspace")
        content = QVBoxLayout(workspace)
        content.setContentsMargins(22, 16, 22, 14)
        content.setSpacing(8)
        self.stack = QStackedWidget()
        self.patient_list_page = self._build_patient_list_page()
        self.new_patient_page = self._build_new_patient_page()
        self.patient_detail_page = self._build_patient_detail_page()
        self.new_study_page = self._build_new_study_page()
        self.measurement_page = self._build_measurement_page()
        self.summary_page = self._build_summary_page()
        from app.respiratory_page import RespiratoryPage
        self.svc_page = RespiratoryPage(self, "svc")
        self.mvv_page = RespiratoryPage(self, "mvv")
        self.calibration_page = self._build_calibration_page()
        self.settings_page = self._build_settings_page()
        for page in (
            self.patient_list_page, self.new_patient_page, self.patient_detail_page,
            self.new_study_page, self.measurement_page, self.summary_page, self.svc_page, self.mvv_page,
            self.calibration_page, self.settings_page,
        ):
            page.layout().setContentsMargins(0, 0, 0, 0)
            page.layout().setSpacing(8)
            self.stack.addWidget(page)
        content.addWidget(self.stack, 1)
        layout.addWidget(workspace, 1)
        self.setCentralWidget(root)
        self.new_patient_button.clicked.connect(self.show_new_patient)
        self.patients_button.clicked.connect(self.show_patients)
        self.study_button.clicked.connect(self.open_current_study)
        self.calibration_button.clicked.connect(lambda: self.stack.setCurrentWidget(self.calibration_page))
        self.settings_button.clicked.connect(lambda: self.stack.setCurrentWidget(self.settings_page))

    def open_current_study(self):
        if self.current_session_id is not None:
            session = db.get_session(self.current_session_id)
            if session is None:
                return
            self.current_patient_id = session['patient_id']
            self.load_study(self.current_session_id)

    def update_navigation(self, *_args):
        page = self.stack.currentWidget()
        study = page in (self.measurement_page, self.svc_page, self.mvv_page, self.summary_page)
        if study and self.study_tabs.parentWidget() != page:
            page.layout().insertWidget(1, self.study_tabs)
            self.study_tabs.show()
        active = (self.study_button if study else self.calibration_button if page == self.calibration_page
                  else self.settings_button if page == self.settings_page else self.patients_button)
        active.setChecked(True)
        self.study_button.setEnabled(self.current_session_id is not None)
        for button, target in ((self.measurement_tab,self.measurement_page),(self.svc_tab,self.svc_page),
                               (self.mvv_tab,self.mvv_page),(self.measurement_summary_tab,self.summary_page)):
            button.setChecked(page == target)
        self.update_device_indicator()

    def update_device_indicator(self):
        ready = self.device_ready
        preparing = self.worker is not None or self.calibration_worker is not None
        self.device_status_label.setText("● Conexión activa" if ready else "Calibración en curso" if self.calibration_worker is not None else "Preparando conexión…" if preparing else "Sin conexión activa")
        self.device_status_label.setProperty('state', 'ready' if ready else 'idle')
        repolish(self.device_status_label)

    @staticmethod
    def _surface():
        frame = role(QFrame(), 'surface')
        return frame

    def _chart_panel(self, title, chart, hint):
        frame = self._surface()
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 12, 12, 8)
        layout.setSpacing(6)
        header = QHBoxLayout()
        header.addWidget(role(QLabel(title), 'sectionTitle'))
        header.addStretch()
        header.addWidget(role(QLabel(hint), 'muted'))
        layout.addLayout(header)
        layout.addWidget(chart, 1)
        return frame

    def _titled_panel(self, title):
        frame = self._surface()
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(20, 16, 20, 20)
        layout.setSpacing(16)
        label = role(QLabel(title), 'sectionTitle')
        layout.addWidget(label)
        return frame, label, layout

    def _make_button(self, text, icon):
        button = QPushButton(text)
        set_button_icon(button, icon)
        return button

    @staticmethod
    def _scroll_content(widget):
        """Keep long pages reachable without increasing the window minimum size."""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(widget)
        # The viewport and the content can retain the system's dark Window
        # brush when QScrollArea itself has a transparent background.
        for surface in (scroll, scroll.viewport(), widget):
            surface.setProperty('scrollBackground', True)
        return scroll

    @staticmethod
    def _patient_heading(name, details):
        heading = QVBoxLayout()
        heading.setContentsMargins(0, 0, 0, 0)
        heading.setSpacing(4)
        heading.setAlignment(Qt.AlignTop)
        for label in (name, details):
            label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
            heading.addWidget(label)
        details.setWordWrap(True)
        return heading

    @staticmethod
    def _set_light_result_palette(table):
        palette = table.palette()
        for role, color in ((QPalette.Base, '#ffffff'), (QPalette.AlternateBase, '#f3f4f6'),
                            (QPalette.Text, '#1f2937'), (QPalette.Highlight, '#bfdbfe'),
                            (QPalette.HighlightedText, '#111827')):
            palette.setColor(role, QColor(color))
        table.setPalette(palette)

    def save_reference_selection(self, *_):
        selection = {key: combo.currentData() for key, combo in self.reference_combos.items()}
        db.set_setting(SETTING, json.dumps(selection))

    def set_reference_selection(self, selection):
        for key, equation in selection.items():
            combo = self.reference_combos[key]
            combo.blockSignals(True)
            combo.setCurrentIndex(combo.findData(equation))
            combo.blockSignals(False)
        self.save_reference_selection()

    def save_fvc_display_settings(self, enabled):
        db.set_setting('fvc_red_abnormal', '1' if enabled else '0')
        self.refresh_study_summary()

    def set_fvc_table_view(self, mode):
        if mode not in ('full', 'compact'):return
        db.set_setting('fvc_table_view', mode)
        with QSignalBlocker(self.maneuver_details_button):
            self.maneuver_details_button.setChecked(mode=='full')
        if hasattr(self,'fvc_table_view_combo'):
            with QSignalBlocker(self.fvc_table_view_combo):
                self.fvc_table_view_combo.setCurrentIndex(self.fvc_table_view_combo.findData(mode))
        self.apply_maneuver_table_view()

    def _color_reference_cells(self, table, row, parameters, references, groups):
        for key, columns in groups.items():
            measured = parameters.get(key)
            reference = (references or {}).get(key) or {}
            lower = reference.get('lln')
            abnormal = (self.fvc_red_values.isChecked() and measured is not None and lower is not None
                        and math.isfinite(measured) and math.isfinite(lower) and measured < lower)
            for column in columns:
                item = table.item(row, column)
                if item is None:
                    continue
                marked = abnormal and item.text() not in ('', '-')
                item.setForeground(QColor('#b91c1c' if marked else '#1f2937'))
                item.setToolTip(f'Por debajo del límite inferior normal: {lower:.3f}' if marked else '')

    def _build_patient_list_page(self):
        root = QWidget()
        layout = QVBoxLayout(root)
        self.patient_search_input = QLineEdit()
        self.patient_search_input.setPlaceholderText("Buscar por nombre, apellido o DNI")
        self.patient_search_input.textChanged.connect(self.filter_patients)
        layout.addWidget(self.patient_search_input)

        self.patient_table = QTableWidget(0, 5)
        self.patient_table.setHorizontalHeaderLabels(["ID", "Nombre", "Apellido", "DNI", "Ultima espirometria"])
        self.patient_table.setColumnHidden(0, True)
        self.patient_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.patient_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.patient_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.patient_table.doubleClicked.connect(lambda _index: self.open_selected_patient())
        layout.addWidget(self.patient_table)

        buttons = QHBoxLayout()
        open_button = self._make_button("Abrir paciente", QStyle.SP_DialogOpenButton)
        edit_button = self._make_button("Editar paciente", QStyle.SP_FileDialogDetailedView)
        open_button.clicked.connect(self.open_selected_patient)
        edit_button.clicked.connect(self.edit_selected_patient)
        buttons.addWidget(open_button)
        buttons.addWidget(edit_button)
        buttons.addStretch()
        layout.addLayout(buttons)
        return root

    def _build_new_patient_page(self):
        root = QWidget()
        layout = QVBoxLayout(root)
        self.patient_form_box, self.patient_form_title, box_layout = self._titled_panel("Nuevo paciente")
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        box_layout.addLayout(form)
        form.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        self.last_name_input = QLineEdit()
        self.first_name_input = QLineEdit()
        self.dni_input = QLineEdit()
        self.birth_date_input = QLineEdit()
        self.birth_date_input.setInputMask("00/00/0000;_")
        self.birth_date_input.setPlaceholderText("DD/MM/AAAA")
        self.sex_input = QComboBox()
        self.sex_input.addItem("", "")
        self.sex_input.addItem("Femenino", "F")
        self.sex_input.addItem("Masculino", "M")
        self.ethnicity_input = QComboBox()
        for key, (label, _value) in ETHNICITY_LABELS.items():
            self.ethnicity_input.addItem(label, key)
        self.ethnicity_input.setCurrentIndex(self.ethnicity_input.findData("caucasian"))
        for widget, width in (
            (self.last_name_input, 260),
            (self.first_name_input, 260),
            (self.dni_input, 120),
            (self.birth_date_input, 120),
            (self.sex_input, 140),
            (self.ethnicity_input, 220),
        ):
            widget.setFixedWidth(width)
        form.addRow("Apellido", self.last_name_input)
        form.addRow("Nombre", self.first_name_input)
        form.addRow("DNI", self.dni_input)
        form.addRow("Fecha nacimiento", self.birth_date_input)
        form.addRow("Sexo", self.sex_input)
        form.addRow("Etnia GLI", self.ethnicity_input)
        self.patient_no_btps = QCheckBox("Sin corrección BTPS (estudio de jeringa)")
        form.addRow(self.patient_no_btps)
        layout.addWidget(self.patient_form_box)

        buttons = QHBoxLayout()
        self.save_patient_button = self._make_button("Guardar paciente", QStyle.SP_DialogSaveButton)
        cancel_button = self._make_button("Cancelar", QStyle.SP_DialogCancelButton)
        self.save_patient_button.clicked.connect(self.save_patient)
        cancel_button.clicked.connect(self.show_patients)
        buttons.addWidget(self.save_patient_button)
        buttons.addWidget(cancel_button)
        buttons.addStretch()
        layout.addLayout(buttons)
        layout.addStretch()
        return root

    def _build_patient_detail_page(self):
        root = QWidget()
        layout = QVBoxLayout(root)
        self.patient_name_label = QLabel()
        self.patient_name_label.setStyleSheet("font-size: 22px; font-weight: 600;")
        self.patient_data_label = QLabel()
        layout.addWidget(self.patient_name_label)
        layout.addWidget(self.patient_data_label)

        studies_header = QHBoxLayout()
        studies_header.addWidget(QLabel("Historial del paciente"))
        studies_header.addStretch()
        new_study_button = self._make_button("Nuevo estudio", QStyle.SP_FileDialogNewFolder)
        new_study_button.clicked.connect(self.show_new_study)
        studies_header.addWidget(new_study_button)
        layout.addLayout(studies_header)

        self.study_table = QTableWidget(0, 2)
        self.study_table.setHorizontalHeaderLabels(["ID", "Fecha y hora de realizacion"])
        self.study_table.setColumnHidden(0, True)
        self.study_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.study_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.study_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.study_table.doubleClicked.connect(lambda _index: self.open_selected_study())
        self.patient_history_tabs = QTabWidget()
        self.patient_history_tabs.addTab(self.study_table, "Estudios")
        from app.history_page import HistoryPage
        self.history_page = HistoryPage(self)
        self.history_page.open_study.connect(self.load_study)
        self.patient_history_tabs.addTab(self.history_page, "Tendencia")
        self.patient_history_tabs.currentChanged.connect(lambda _: self.update_navigation())
        layout.addWidget(self.patient_history_tabs)
        return root

    def _build_new_study_page(self):
        root = QWidget()
        layout = QVBoxLayout(root)
        box, _, box_layout = self._titled_panel("Nuevo estudio")
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setFieldGrowthPolicy(QFormLayout.FieldsStayAtSizeHint)
        self.study_age_label = QLabel("-")
        self.study_weight_input = QLineEdit()
        self.study_height_input = QLineEdit()
        self.study_age_label.setFixedWidth(120)
        self.study_weight_input.setFixedWidth(92)
        self.study_height_input.setFixedWidth(92)
        form.addRow("Edad", self.study_age_label)
        form.addRow("Peso kg", self.study_weight_input)
        form.addRow("Altura cm", self.study_height_input)
        box_layout.addLayout(form)
        layout.addWidget(box)

        buttons = QHBoxLayout()
        start_study_button = self._make_button("Iniciar estudio", QStyle.SP_MediaPlay)
        back_button = self._make_button("Volver", QStyle.SP_ArrowBack)
        start_study_button.clicked.connect(self.start_study)
        back_button.clicked.connect(self.show_patient_detail)
        buttons.addWidget(start_study_button)
        buttons.addWidget(back_button)
        buttons.addStretch()
        layout.addLayout(buttons)
        layout.addStretch()
        return root

    def _build_measurement_page(self):
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setSpacing(10)
        header = QHBoxLayout()
        self.measurement_patient_label = role(QLabel(), 'pageTitle')
        self.measurement_patient_data_label = role(QLabel(), 'muted')
        header.addLayout(self._patient_heading(self.measurement_patient_label,
                                              self.measurement_patient_data_label), 1)
        self.measurement_date_label = role(QLabel("Estudio FVC"), 'muted')
        self.measurement_date_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        layout.addLayout(header)

        self.study_tabs = QWidget()
        tabs = QHBoxLayout(self.study_tabs)
        tabs.setContentsMargins(0, 0, 0, 0)
        tabs.setSpacing(16)
        self.measurement_tab = role(QPushButton("FVC"), 'studyTab')
        self.measurement_summary_tab = role(QPushButton("Sumario"), 'studyTab')
        self.svc_tab = role(QPushButton("SVC"), "studyTab")
        self.mvv_tab = role(QPushButton("MVV"), "studyTab")
        self.svc_tab.clicked.connect(lambda: self.open_additional_measurement(self.svc_page))
        self.mvv_tab.clicked.connect(lambda: self.open_additional_measurement(self.mvv_page))
        for button in (self.measurement_tab, self.svc_tab, self.mvv_tab, self.measurement_summary_tab):
            button.setCheckable(True)
            tabs.addWidget(button)
        self.measurement_tab.setChecked(True)
        self.measurement_tab.clicked.connect(lambda: self.stack.setCurrentWidget(self.measurement_page))
        self.measurement_summary_tab.clicked.connect(self.show_summary)
        tabs.addStretch()
        layout.addWidget(self.study_tabs)

        toolbar = QHBoxLayout()
        toolbar.addWidget(role(QLabel("Fase del estudio"), 'muted'))
        self.phase_selector = PhaseSelector()
        self.phase_selector.addItem("PRE", "pre")
        self.phase_selector.addItem("POST", "post")
        self.phase_selector.currentIndexChanged.connect(self.phase_changed)
        toolbar.addWidget(self.phase_selector)
        self.session_quality_label = role(QLabel('Realizá una maniobra'), 'sessionQuality')
        self.session_quality_label.setWordWrap(True)
        self.session_quality_label.setProperty('state', 'empty')
        toolbar.addWidget(self.session_quality_label, 1)
        toolbar.addStretch()
        toolbar.addWidget(self.measurement_date_label)
        self.status_label = StatusLabel("Listo")
        self.status_label.setMinimumWidth(240)
        self.status_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        toolbar.addWidget(self.status_label)
        layout.addLayout(toolbar)

        self.measurement_splitter = QSplitter(Qt.Vertical)
        self.measurement_splitter.setChildrenCollapsible(False)
        charts_root = QWidget()
        chart_column = QVBoxLayout(charts_root)
        chart_column.setContentsMargins(0, 0, 0, 0)
        chart_column.setSpacing(6)
        charts = QHBoxLayout()
        charts.setContentsMargins(0, 0, 0, 0)
        charts.setSpacing(12)
        self.flow_volume_chart = CurveWidget("flow_volume")
        self.volume_time_chart = CurveWidget("volume_time")
        charts.addWidget(self._chart_panel("Flujo–volumen", self.flow_volume_chart, "Flujo en L/s"), 1)
        charts.addWidget(self._chart_panel("Volumen–tiempo", self.volume_time_chart, "Volumen en L"), 1)
        chart_column.addLayout(charts, 1)
        self.curve_legend_label = role(QLabel(""), "muted")
        self.curve_legend_label.setTextFormat(Qt.RichText)
        self.curve_legend_label.setWordWrap(True)
        self.curve_legend_label.hide()
        chart_column.addWidget(self.curve_legend_label)

        result_panel = self._surface()
        result_layout = QVBoxLayout(result_panel)
        result_layout.setContentsMargins(0, 0, 0, 0)
        result_layout.setSpacing(0)
        result_header = QHBoxLayout()
        result_header.setContentsMargins(14, 8, 14, 4)
        result_header.addWidget(role(QLabel("Maniobras"), 'sectionTitle'))
        self.maneuver_count_label = role(QLabel("Sin maniobras"), 'muted')
        result_header.addSpacing(12)
        result_header.addWidget(self.maneuver_count_label)
        result_header.addStretch()
        self.maneuver_details_button = role(QPushButton("Ver más parámetros"), 'link')
        self.maneuver_details_button.setCheckable(True)
        self.maneuver_details_button.setChecked(db.get_setting('fvc_table_view','full')!='compact')
        self.maneuver_details_button.toggled.connect(lambda checked:self.set_fvc_table_view('full' if checked else 'compact'))
        result_header.addWidget(self.maneuver_details_button)
        result_layout.addLayout(result_header)
        self.maneuver_table = QTableWidget(0, 18)
        self.maneuver_table.setObjectName("maneuverTable")
        self.maneuver_table.setItemDelegate(PhaseTableDelegate(self.maneuver_table))
        self._set_light_result_palette(self.maneuver_table)
        self.maneuver_table.setHorizontalHeaderLabels([
            "ID", "Hora", "Incluir", "Imprimir", "FVC (L)", "FVC % teo", "FVC z",
            "FEV1 (L)", "FEV1 % teo", "FEV1 z", "FEV1/FVC", "Rel z",
            "FEF 25–75", "FEF % teo", "FEF z", "PEF (L/s)", "Duración (s)", "Calidad",
        ])
        self.maneuver_table.setColumnHidden(0, True)
        self.maneuver_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.maneuver_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.maneuver_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.maneuver_table.setShowGrid(False)
        self.maneuver_table.verticalHeader().setVisible(False)
        self.maneuver_table.verticalHeader().setDefaultSectionSize(33)
        self.maneuver_table.horizontalHeader().setSectionResizeMode(QHeaderView.Fixed)
        self.maneuver_table.horizontalHeader().setSectionResizeMode(17, QHeaderView.Stretch)
        for col, width in {1:96, 2:58, 3:66, 4:84, 5:90, 6:65, 7:84, 8:90, 9:65,
                           10:92, 11:65, 12:88, 13:90, 14:65, 15:90, 16:90}.items():
            self.maneuver_table.setColumnWidth(col, width)
        self.maneuver_table.setMinimumHeight(88)
        self.maneuver_table.itemChanged.connect(self.maneuver_item_changed)
        self.maneuver_table.itemSelectionChanged.connect(self.highlight_selected_maneuver)
        result_layout.addWidget(self.maneuver_table, 1)
        self.measurement_splitter.addWidget(result_panel)
        self.measurement_splitter.addWidget(charts_root)
        self.measurement_splitter.setStretchFactor(0, 3)
        self.measurement_splitter.setStretchFactor(1, 2)
        self.measurement_splitter.setSizes([340, 300])
        layout.addWidget(self.measurement_splitter, 1)
        self.apply_maneuver_table_view()

        controls = QHBoxLayout()
        controls.setSpacing(10)
        self.maneuver_button = role(self._make_button("Iniciar maniobra", QStyle.SP_MediaPlay), 'primary')
        self.maneuver_button.clicked.connect(self.toggle_maneuver)
        self.maneuver_button.setToolTip("Barra espaciadora: iniciar o finalizar la maniobra")
        self.maneuver_button.setAccessibleDescription("Barra espaciadora para iniciar o finalizar")
        controls.addWidget(self.maneuver_button)
        self.elapsed_label = role(QLabel("0 s"), 'timer')
        self.elapsed_label.setAlignment(Qt.AlignCenter)
        controls.addWidget(self.elapsed_label)
        self.zero_button = self._make_button("Flujo cero", QStyle.SP_BrowserReload)
        self.zero_button.clicked.connect(self.repeat_zero)
        controls.addWidget(self.zero_button)
        self.delete_button = role(self._make_button("Borrar excluidas", QStyle.SP_TrashIcon), 'link')
        self.delete_button.setEnabled(False)
        self.delete_button.clicked.connect(self.delete_excluded_maneuvers)
        controls.addWidget(self.delete_button)
        header.addLayout(controls)
        self.maneuver_space_shortcut = QShortcut(QKeySequence(Qt.Key_Space), root)
        self.maneuver_space_shortcut.setAutoRepeat(False)
        self.maneuver_space_shortcut.setEnabled(False)
        self.maneuver_space_shortcut.activated.connect(self.space_maneuver)
        self.elapsed_timer = QTimer(self)
        self.elapsed_timer.timeout.connect(self.update_elapsed_time)
        return root

    def apply_maneuver_table_view(self, *_args):
        expanded = self.maneuver_details_button.isChecked()
        self.maneuver_details_button.setText("Vista compacta" if expanded else "Ver más parámetros")
        self.maneuver_table.verticalHeader().setDefaultSectionSize(26)
        for column in (5, 6, 8, 9, 11, 12, 13, 14, 16):
            self.maneuver_table.setColumnHidden(column, not expanded)
        count = 0
        for row in range(self.maneuver_table.rowCount()):
            maneuver = self._row_is_maneuver(row)
            phase = self._phase_for_row(row) if maneuver else None
            if maneuver and phase == self.current_phase:
                count += 1
            self.maneuver_table.setRowHidden(row, False)
        self.maneuver_count_label.setText(f"{count} {self.current_phase.upper()} registradas")

    def highlight_selected_maneuver(self):
        if hasattr(self, 'flow_volume_chart') and not self.updating_maneuver_table and not self.capture_active:
            self.refresh_visible_curves()

    def review_selected_quality(self):
        row = self.maneuver_table.currentRow()
        if self.capture_active or not self._row_is_maneuver(row):
            return
        key = int(self.maneuver_table.item(row, 0).text())
        record = next(m for m in db.list_maneuvers_for_session(self.current_session_id) if m['id'] == key)
        params = quality_processing(record)
        if params.get('origin') == 'breeze':
            QMessageBox.information(self, 'Calidad original', 'Este estudio conserva la calidad exportada por Breeze; no se reanalizan sus curvas.')
            return
        if params.get('quality_version') != 1:
            if not params.get('vol_curve'):
                QMessageBox.information(self, 'Calidad', 'No hay una curva espiratoria guardada para evaluar los artefactos.')
                return
            params = annotate_quality(params)
        self.flow_volume_chart.set_quality_regions(plot_regions(params, acquisition=True))
        self.volume_time_chart.set_quality_regions(plot_regions(params))
        from app.quality_dialog import QualityReviewDialog
        dialog = QualityReviewDialog(params, self)
        try:
            if dialog.exec() == QDialog.Accepted:
                db.review_maneuver_quality(key, params, dialog.decisions())
                updated = next(m for m in db.list_maneuvers_for_session(self.current_session_id) if m['id'] == key)
                text = quality_text(quality_processing(updated))
                item = self.maneuver_table.item(self._row_for_maneuver(key), 17)
                item.setText(text)
                item.setToolTip(text)
                self.refresh_study_summary()
        except ValueError as exc:
            QMessageBox.warning(self, 'Revisión de calidad', str(exc))
        finally:
            self.refresh_visible_curves()
            dialog.deleteLater()

    def _build_summary_page(self):
        root = QWidget()
        layout = QVBoxLayout(root)

        header = QHBoxLayout()
        self.summary_patient_label = QLabel()
        role(self.summary_patient_label, 'pageTitle')
        self.summary_patient_data_label = role(QLabel(), "muted")
        print_button = self._make_button("Imprimir", QStyle.SP_DialogSaveButton)
        print_button.clicked.connect(self.preview_report)
        save_pdf_button = self._make_button("Guardar PDF", QStyle.SP_DialogSaveButton)
        role(save_pdf_button, "primary")
        save_pdf_button.clicked.connect(self.save_report_pdf)
        header.addLayout(self._patient_heading(self.summary_patient_label,
                                              self.summary_patient_data_label), 1)
        header.addWidget(print_button)
        header.addWidget(save_pdf_button)
        layout.addLayout(header)

        body = QWidget()
        self.summary_scroll = self._scroll_content(body)
        layout.addWidget(self.summary_scroll, 1)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.summary_table = QTableWidget(0, 9)
        self._set_light_result_palette(self.summary_table)
        self.summary_table.setHorizontalHeaderLabels(
            ["Parametro", "Predicho", "PRE", "PRE % teo", "PRE z", "POST", "POST % teo", "POST z", "% cambio"]
        )
        self.summary_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.summary_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.summary_table.verticalHeader().setDefaultSectionSize(28)
        self.summary_table.verticalHeader().hide()
        self.summary_table.setShowGrid(False)
        self.summary_table.setMinimumHeight(190)
        layout.addWidget(self.summary_table)

        self.summary_zscore_chart = ZScoreWidget()
        layout.addWidget(self.summary_zscore_chart)
        self.summary_reference_note = QLabel(REFERENCE_NOTE)
        self.summary_reference_note.setWordWrap(True)
        role(self.summary_reference_note, "muted")
        self.summary_reference_note.hide()
        layout.addWidget(self.summary_reference_note)

        charts = QHBoxLayout()
        self.summary_flow_volume_chart = CurveWidget("flow_volume")
        self.summary_volume_time_chart = CurveWidget("volume_time")
        charts.addWidget(self._chart_panel("Flujo / volumen", self.summary_flow_volume_chart, "L/s · L"))
        charts.addWidget(self._chart_panel("Volumen / tiempo", self.summary_volume_time_chart, "L · s"))
        layout.addLayout(charts, 1)

        report_controls = QHBoxLayout()
        report_controls.addWidget(QLabel("Informe"))
        report_controls.addStretch()
        self.auto_report_button = self._make_button("Interpretación automática", QStyle.SP_FileDialogDetailedView)
        self.auto_report_button.clicked.connect(self.preview_auto_report)
        report_controls.addWidget(self.auto_report_button)
        layout.addLayout(report_controls)
        self.summary_report_input = QTextEdit()
        self.summary_report_input.setPlaceholderText("Escribir informe del estudio")
        self.summary_report_input.setMinimumHeight(80)
        self.summary_report_input.setMaximumHeight(130)
        self.summary_report_input.textChanged.connect(self.save_summary_report)
        layout.addWidget(self.summary_report_input)
        return root

    def _build_calibration_page(self):
        root = QWidget()
        layout = QVBoxLayout(root)
        top = QHBoxLayout()
        self.calibration_status_label = QLabel("Listo")
        self.calibration_status_label.setStyleSheet("font-size: 18px; font-weight: 600;")
        top.addWidget(self.calibration_status_label)
        top.addStretch()
        self.calibration_start_button = role(self._make_button("Iniciar calibracion", QStyle.SP_MediaPlay), "primary")
        self.calibration_stop_button = self._make_button("Finalizar calibracion", QStyle.SP_MediaStop)
        self.calibration_stop_button.setEnabled(False)
        self.calibration_reset_button = self._make_button("Reiniciar", QStyle.SP_BrowserReload)
        self.calibration_save_button = self._make_button("Guardar calibracion", QStyle.SP_DialogSaveButton)
        self.calibration_save_button.setEnabled(False)
        for button in (
            self.calibration_start_button,
            self.calibration_stop_button,
            self.calibration_reset_button,
            self.calibration_save_button,
        ):
            top.addWidget(button)
        layout.addLayout(top)

        inputs = QHBoxLayout()
        self.calibration_volume_input = QLineEdit("3.0")
        self.calibration_temp_input = QLineEdit(str(spirometry._cal.get("temperatura_C") or ""))
        self.calibration_pressure_input = QLineEdit(str(spirometry._cal.get("presion_mmHg") or ""))
        self.calibration_humidity_input = QLineEdit(str(spirometry._cal.get("humedad_pct") or ""))
        for label, widget in (
            ("Volumen jeringa (L)", self.calibration_volume_input),
            ("Temperatura (C)", self.calibration_temp_input),
            ("Presion (mmHg)", self.calibration_pressure_input),
            ("Humedad (%)", self.calibration_humidity_input),
        ):
            inputs.addWidget(QLabel(label))
            widget.setMaximumWidth(92)
            widget.textChanged.connect(self.refresh_calibration_result)
            inputs.addWidget(widget)
        inputs.addStretch()
        layout.addLayout(inputs)

        body = QHBoxLayout()
        self.calibration_table = QTableWidget(0, 6)
        self.calibration_table.setHorizontalHeaderLabels(["N", "Tipo", "Vol (L)", "Pico", "Dur. (s)", "Error"])
        self.calibration_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.calibration_table.verticalHeader().setVisible(False)
        self.calibration_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.calibration_table.setMinimumWidth(320)
        self.calibration_table.setMaximumWidth(480)
        body.addWidget(self.calibration_table, 2)
        self.calibration_chart = CurveWidget("volume_time")
        self.calibration_chart.calibration_mode = True
        body.addWidget(self.calibration_chart, 3)
        layout.addLayout(body, 1)

        self.calibration_result_label = QLabel(
            ("Pendiente de calibrar con jeringa" if spirometry._cal.get("fecha") == "pendiente" else
             f"Actual: esp {spirometry.FACTOR_ESP:.6f}    ins {spirometry.FACTOR_INS:.6f}")
        )
        layout.addWidget(self.calibration_result_label)
        self.calibration_start_button.clicked.connect(self.start_calibration_session)
        self.calibration_stop_button.clicked.connect(self.stop_calibration_session)
        self.calibration_reset_button.clicked.connect(self.reset_calibration)
        self.calibration_save_button.clicked.connect(self.save_calibration)
        return root

    def _build_settings_page(self):
        root = QWidget()
        layout = QVBoxLayout(root)
        tabs = QTabWidget()

        fvc_tab = QWidget()
        fvc_layout = QVBoxLayout(fvc_tab)
        table_view_row=QHBoxLayout()
        table_view_row.addWidget(QLabel('Vista de la tabla de maniobras'))
        self.fvc_table_view_combo=QComboBox()
        self.fvc_table_view_combo.setProperty('referenceSelector',True)
        self.fvc_table_view_combo.addItem('Total','full')
        self.fvc_table_view_combo.addItem('Compacta','compact')
        self.fvc_table_view_combo.setCurrentIndex(1 if db.get_setting('fvc_table_view','full')=='compact' else 0)
        self.fvc_table_view_combo.currentIndexChanged.connect(lambda _:self.set_fvc_table_view(self.fvc_table_view_combo.currentData()))
        table_view_row.addWidget(self.fvc_table_view_combo)
        table_view_row.addStretch()
        fvc_layout.addLayout(table_view_row)
        self.fvc_red_values = QCheckBox("Mostrar en rojo los valores por debajo del límite normal")
        self.fvc_red_values.setChecked(db.get_setting('fvc_red_abnormal', '0') == '1')
        self.fvc_red_values.toggled.connect(self.save_fvc_display_settings)
        fvc_layout.addWidget(self.fvc_red_values)
        explanation = QLabel("Usa el límite inferior normal de la ecuación elegida para cada parámetro. "
                             "Se aplica a las tablas de maniobras y sumario cuando hay referencia disponible.")
        explanation.setWordWrap(True)
        fvc_layout.addWidget(explanation)
        equation_group, _, equation_layout = self._titled_panel("Ecuaciones de referencia por parámetro")
        equation_form = QFormLayout()
        selection = configured_selection(db.get_setting(SETTING))
        self.reference_combos = {}
        for key, label in PARAMETERS.items():
            combo = QComboBox()
            combo.setObjectName("reference_" + key)
            combo.setProperty("referenceSelector", True)
            for equation in SUPPORTED[key]:
                combo.addItem(EQUATIONS[equation], equation)
            combo.setCurrentIndex(combo.findData(selection[key]))
            self.reference_combos[key] = combo
            equation_form.addRow(label, combo)
        equation_layout.addLayout(equation_form)
        reference_help = QLabel(
            "Se guarda automáticamente y se aplica a estudios nuevos. Los estudios anteriores "
            "conservan sus referencias. GLI Global no utiliza etnia; GLI-2012 usa la etnia de la ficha "
            "al crear el estudio. Sin datos válidos o fuera del rango de edad se muestra «–». "
            "GLI 2021 (SVC/IC/ERV): 5–80 años y ascendencia europea declarada en la ficha. "
            "SVC puede usar el predicho de FVC, sin trasladar su LIN/z-score. "
            "MVV: compatibilidad Breeze, sólo predicho y %. Polgar: 7–17; Zapletal2: 6–18 años y talla 107–182 cm; "
            "ITS: adultos, límite superior de edad no validado. PEF: sin referencia implementada.")
        reference_help.setWordWrap(True)
        equation_layout.addWidget(reference_help)
        presets = QHBoxLayout()
        recommended = QPushButton("GLI Global + GLI-2012 para FEF 25–75")
        recommended.clicked.connect(lambda: self.set_reference_selection({k:RECOMMENDED[k] for k in FVC_PARAMETERS}))
        legacy = QPushButton("GLI-2012")
        legacy.clicked.connect(lambda: self.set_reference_selection({k:LEGACY[k] for k in FVC_PARAMETERS}))
        presets.addWidget(recommended)
        presets.addWidget(legacy)
        presets.addStretch()
        equation_layout.addLayout(presets)
        fvc_layout.addWidget(equation_group)
        for combo in self.reference_combos.values():
            combo.currentIndexChanged.connect(self.save_reference_selection)
        fvc_layout.addStretch()
        tabs.addTab(self._scroll_content(fvc_tab), "FVC")

        transfer_tab = QWidget()
        transfer_layout = QVBoxLayout(transfer_tab)
        transfer_text = QLabel("Importá estudios de Breeze o trasladá estudios entre instalaciones de esta aplicación. "
                              "Los resultados históricos se conservan sin recalcular ni volver a aplicar BTPS.")
        transfer_text.setWordWrap(True)
        transfer_layout.addWidget(transfer_text)
        import_button = self._make_button("Importar estudios desde una carpeta…", QStyle.SP_DialogOpenButton)
        export_button = self._make_button("Exportar estudios (.espiro)…", QStyle.SP_DialogSaveButton)
        import_button.clicked.connect(lambda: self.open_transfer(False))
        export_button.clicked.connect(lambda: self.open_transfer(True))
        transfer_layout.addWidget(import_button)
        transfer_layout.addWidget(export_button)
        transfer_note = QLabel("La importación muestra una vista previa y omite duplicados por defecto. "
                              "El archivo .espiro incluye datos personales, informes, resultados y curvas; "
                              "no cambia la calibración del equipo ni la configuración de esta instalación.")
        transfer_note.setWordWrap(True)
        transfer_layout.addWidget(transfer_note)
        transfer_layout.addStretch()
        tabs.addTab(self._scroll_content(transfer_tab), "Importar / exportar")

        report_tab = QWidget()
        report_layout = QVBoxLayout(report_tab)
        form = QFormLayout()
        self.report_header_input = QTextEdit()
        self.report_header_input.setAcceptRichText(True)
        self.report_header_input.setMinimumHeight(96)
        self.report_header_input.setHtml(
            self._normalize_report_header_html(
                db.get_setting("report_header_html", self._default_report_header_html())
            )
        )
        header_tools = QVBoxLayout()
        bold_button = self._make_button("Negrita", QStyle.SP_DialogApplyButton)
        bold_button.clicked.connect(self.toggle_report_header_bold)
        left_button = self._make_button("Izquierda", QStyle.SP_ArrowLeft)
        left_button.clicked.connect(lambda: self.align_report_header(Qt.AlignLeft))
        center_button = self._make_button("Centro", QStyle.SP_FileDialogDetailedView)
        center_button.clicked.connect(lambda: self.align_report_header(Qt.AlignCenter))
        right_button = self._make_button("Derecha", QStyle.SP_ArrowRight)
        right_button.clicked.connect(lambda: self.align_report_header(Qt.AlignRight))
        apply_all_button = self._make_button("Aplicar a todo", QStyle.SP_DialogApplyButton)
        apply_all_button.clicked.connect(self.apply_report_header_format_to_all)
        self.report_font_family_input = QComboBox()
        self.report_font_family_input.addItem("Sans serif", "Sans Serif")
        self.report_font_family_input.addItem("Serif", "Serif")
        self.report_font_family_input.addItem("Monoespaciada", "Monospace")
        self.report_font_family_input.currentIndexChanged.connect(self.set_report_header_font_family)
        self.report_font_size_input = QSpinBox()
        self.report_font_size_input.setRange(8, 28)
        self.report_font_size_input.setValue(18)
        self.report_font_size_input.valueChanged.connect(self.set_report_header_font_size)
        self.report_line_height_input = QSpinBox()
        self.report_line_height_input.setRange(70, 160)
        self.report_line_height_input.setSuffix("%")
        self.report_line_height_input.setValue(int(db.get_setting("report_header_line_height", "85")))
        self.report_line_height_input.valueChanged.connect(self.set_report_header_line_height)
        format_buttons = QHBoxLayout()
        for widget in (bold_button, left_button, center_button, right_button, apply_all_button):
            format_buttons.addWidget(widget)
        format_buttons.addStretch()
        header_tools.addLayout(format_buttons)
        font_tools = QHBoxLayout()
        for widget in (QLabel("Fuente"), self.report_font_family_input, QLabel("Tamaño"),
                       self.report_font_size_input, QLabel("Interlineado"), self.report_line_height_input):
            font_tools.addWidget(widget)
        font_tools.addStretch()
        header_tools.addLayout(font_tools)
        header_tools_container = QWidget()
        header_tools_container.setLayout(header_tools)
        form.addRow("", header_tools_container)
        form.addRow("Encabezado", self.report_header_input)

        logo_row = QHBoxLayout()
        self.report_logo_input = QLineEdit(db.get_setting("report_logo_path", "") or "")
        logo_button = self._make_button("Seleccionar imagen", QStyle.SP_DialogOpenButton)
        logo_button.clicked.connect(self.select_report_logo)
        logo_row.addWidget(self.report_logo_input)
        logo_row.addWidget(logo_button)
        logo_container = QWidget()
        logo_container.setLayout(logo_row)
        form.addRow("Imagen", logo_container)

        self.report_paper_size_input = QComboBox()
        self.report_paper_size_input.addItem("A4", "A4")
        self.report_paper_size_input.addItem("Legal", "Legal")
        self.report_paper_size_input.addItem("Carta", "Letter")
        saved_paper = db.get_setting("report_paper_size", "A4")
        self.report_paper_size_input.setCurrentIndex(self.report_paper_size_input.findData(saved_paper))
        form.addRow("Papel", self.report_paper_size_input)
        margin_row = QGridLayout()
        self.report_margin_left_input = QSpinBox()
        self.report_margin_left_input.setRange(5, 40)
        self.report_margin_left_input.setSuffix(" mm")
        self.report_margin_left_input.setValue(int(db.get_setting("report_margin_left_mm", "12")))
        self.report_margin_top_input = QSpinBox()
        self.report_margin_top_input.setRange(5, 40)
        self.report_margin_top_input.setSuffix(" mm")
        self.report_margin_top_input.setValue(int(db.get_setting("report_margin_top_mm", "6")))
        self.report_margin_right_input = QSpinBox()
        self.report_margin_right_input.setRange(5, 40)
        self.report_margin_right_input.setSuffix(" mm")
        self.report_margin_right_input.setValue(int(db.get_setting("report_margin_right_mm", "12")))
        self.report_margin_bottom_input = QSpinBox()
        self.report_margin_bottom_input.setRange(5, 40)
        self.report_margin_bottom_input.setSuffix(" mm")
        self.report_margin_bottom_input.setValue(int(db.get_setting("report_margin_bottom_mm", "12")))
        for i, (label, field) in enumerate((("Izquierdo", self.report_margin_left_input),
                ("Superior", self.report_margin_top_input), ("Derecho", self.report_margin_right_input),
                ("Inferior", self.report_margin_bottom_input))):
            margin_row.addWidget(QLabel(label), i // 2, (i % 2) * 2)
            margin_row.addWidget(field, i // 2, (i % 2) * 2 + 1)
        margin_container = QWidget()
        margin_container.setLayout(margin_row)
        form.addRow("Margenes de pagina", margin_container)
        report_layout.addLayout(form)
        save_button = self._make_button("Guardar configuracion", QStyle.SP_DialogSaveButton)
        save_button.clicked.connect(self.save_report_settings)
        report_layout.addWidget(save_button)
        report_layout.addStretch()
        tabs.addTab(self._scroll_content(report_tab), "Informe")

        layout.addWidget(tabs)
        return root

    def open_transfer(self, exporting=False):
        if self.capture_active or self.calibration_worker is not None:
            QMessageBox.information(self, "Estudios", "Finalizá la captura o calibración antes de trasladar estudios.")
            return
        dialog = TransferDialog(self, exporting=exporting)
        dialog.exec()
        if dialog.changed:
            self.refresh_patients()
            if self.current_session_id is not None and db.get_session(self.current_session_id) is None:
                self.current_session_id = None
        dialog.deleteLater()

    def select_report_logo(self):
        dialog = file_dialog(self, "Seleccionar imagen", "Imagenes (*.png *.jpg *.jpeg *.bmp)")
        path = dialog.selectedFiles()[0] if dialog.exec() == QDialog.Accepted else ""
        dialog.deleteLater()
        if path:
            self.report_logo_input.setText(path)

    def toggle_report_header_bold(self):
        fmt = QTextCharFormat()
        fmt.setFontWeight(QFont.Normal if self.report_header_input.fontWeight() > QFont.Normal else QFont.Bold)
        self._merge_report_header_format(fmt)

    def set_report_header_font_size(self, size):
        fmt = QTextCharFormat()
        fmt.setFontPointSize(size)
        self._merge_report_header_format(fmt)

    def set_report_header_font_family(self, *_args):
        fmt = QTextCharFormat()
        fmt.setFontFamily(self.report_font_family_input.currentData())
        self._merge_report_header_format(fmt)

    def set_report_header_line_height(self, percent):
        cursor = self.report_header_input.textCursor()
        block_fmt = QTextBlockFormat()
        block_fmt.setLineHeight(float(percent), QTextBlockFormat.ProportionalHeight.value)
        block_fmt.setTopMargin(0)
        block_fmt.setBottomMargin(0)
        if cursor.hasSelection():
            cursor.mergeBlockFormat(block_fmt)
        else:
            cursor.select(QTextCursor.BlockUnderCursor)
            cursor.mergeBlockFormat(block_fmt)
        self.report_header_input.setTextCursor(cursor)

    def align_report_header(self, alignment):
        cursor = self.report_header_input.textCursor()
        block_fmt = QTextBlockFormat()
        block_fmt.setAlignment(alignment)
        block_fmt.setTopMargin(0)
        block_fmt.setBottomMargin(0)
        cursor.mergeBlockFormat(block_fmt)
        self.report_header_input.setTextCursor(cursor)

    def _merge_report_header_format(self, fmt):
        cursor = self.report_header_input.textCursor()
        if not cursor.hasSelection():
            cursor.select(QTextCursor.BlockUnderCursor)
            block_fmt = QTextBlockFormat()
            block_fmt.setHeadingLevel(0)
            block_fmt.setTopMargin(0)
            block_fmt.setBottomMargin(0)
            cursor.mergeBlockFormat(block_fmt)
        cursor.mergeCharFormat(fmt)
        self.report_header_input.mergeCurrentCharFormat(fmt)

    def apply_report_header_format_to_all(self):
        cursor = QTextCursor(self.report_header_input.document())
        cursor.select(QTextCursor.Document)
        char_fmt = QTextCharFormat()
        char_fmt.setFontFamily(self.report_font_family_input.currentData())
        char_fmt.setFontPointSize(self.report_font_size_input.value())
        cursor.mergeCharFormat(char_fmt)
        block_fmt = QTextBlockFormat()
        block_fmt.setTopMargin(0)
        block_fmt.setBottomMargin(0)
        block_fmt.setLineHeight(float(self.report_line_height_input.value()), QTextBlockFormat.ProportionalHeight.value)
        cursor.mergeBlockFormat(block_fmt)

    def save_report_settings(self):
        self._compact_report_header_blocks()
        db.set_setting("report_header_html", self.report_header_input.toHtml())
        db.set_setting("report_logo_path", self.report_logo_input.text().strip())
        db.set_setting("report_paper_size", self.report_paper_size_input.currentData())
        db.set_setting("report_header_line_height", str(self.report_line_height_input.value()))
        db.set_setting("report_margin_left_mm", str(self.report_margin_left_input.value()))
        db.set_setting("report_margin_top_mm", str(self.report_margin_top_input.value()))
        db.set_setting("report_margin_right_mm", str(self.report_margin_right_input.value()))
        db.set_setting("report_margin_bottom_mm", str(self.report_margin_bottom_input.value()))
        QMessageBox.information(self, "Configuracion", "Configuracion guardada.")

    def _compact_report_header_blocks(self):
        cursor = QTextCursor(self.report_header_input.document())
        cursor.select(QTextCursor.Document)
        block_fmt = QTextBlockFormat()
        block_fmt.setTopMargin(0)
        block_fmt.setBottomMargin(0)
        block_fmt.setLineHeight(float(self.report_line_height_input.value()), QTextBlockFormat.ProportionalHeight.value)
        block_fmt.setHeadingLevel(0)
        cursor.mergeBlockFormat(block_fmt)

    @staticmethod
    def _default_report_header_html():
        return "<p style='font-size:18pt; font-weight:700; text-align:center; margin:0;'>Informe espirometria</p>"

    @staticmethod
    def _normalize_report_header_html(html):
        return (
            html.replace("<h1", "<p")
            .replace("</h1>", "</p>")
            .replace("<h2", "<p")
            .replace("</h2>", "</p>")
            .replace("<h3", "<p")
            .replace("</h3>", "</p>")
        )

    def show_patients(self):
        self.editing_patient_id = None
        self.patient_search_input.clear()
        self.refresh_patients()
        self.stack.setCurrentWidget(self.patient_list_page)

    def start_calibration_session(self):
        if self.calibration_worker is not None:
            return
        if self.worker is not None:
            self._pending_calibration_start = True
            self._device_requested = False
            self.worker.shutdown()
            self.calibration_status_label.setText("Liberando el espirómetro del estudio")
            return
        # A new acquisition must not reuse strokes from the previous session.
        # Saved calibration factors remain active in spirometry.
        self.reset_calibration()
        self.calibration_thread = QThread()
        inputs = self._calibration_inputs()
        environment = (dict(zip(('syringe_volume_L', 'temperature_C', 'pressure_mmHg', 'humidity_pct'), inputs))
                       if inputs is not None else None)
        self.calibration_worker = CalibrationSessionWorker(environment=environment)
        self.calibration_worker.moveToThread(self.calibration_thread)
        self.calibration_thread.started.connect(self.calibration_worker.run)
        self.calibration_worker.status.connect(self.calibration_status_label.setText)
        self.calibration_worker.progress.connect(self.update_live_calibration_curve)
        self.calibration_worker.stroke_finished.connect(self.calibration_stroke_finished)
        self.calibration_worker.ready.connect(self.calibration_session_ready)
        self.calibration_worker.failed.connect(self.calibration_failed)
        self.calibration_worker.recording_saved.connect(self.calibration_recording_saved)
        self.calibration_worker.closed.connect(self.calibration_thread.quit)
        self.calibration_worker.failed.connect(self.calibration_thread.quit)
        self.calibration_thread.finished.connect(self.calibration_thread_finished)
        self.calibration_start_button.setEnabled(False)
        self.update_device_indicator()
        self.calibration_thread.start()

    def calibration_session_ready(self):
        self.calibration_stop_button.setEnabled(True)

    def calibration_recording_saved(self, path):
        self.last_calibration_recording = path
        self.calibration_status_label.setToolTip(f"Registro de esta sesión: {path}")

    def stop_calibration_session(self):
        if self.calibration_worker is not None:
            self.calibration_worker.shutdown()

    def update_live_calibration_curve(self, point):
        self.live_calibration_curve.append(point)
        curves = [stroke["curva"] for stroke in self.calibration_strokes if stroke.get("curva")]
        self.calibration_chart.set_curves([*curves, self.live_calibration_curve])

    def calibration_stroke_finished(self, stroke):
        if not stroke:
            if self.calibration_worker is not None:
                self.live_calibration_curve = []
            return
        else:
            self.calibration_strokes.append(stroke)
            self.refresh_calibration_table()
            self.refresh_calibration_result()
            self.calibration_status_label.setText("Golpe guardado")
        self.live_calibration_curve = []

    def calibration_failed(self, trace):
        if "Cero inestable o fuera de rango:" in trace:
            self.calibration_status_label.setText("Repetir puesta a cero")
            QMessageBox.warning(self, "Puesta a cero incompleta",
                                self._device_error_message(trace, zero_action="Iniciar calibracion"))
            return
        self.calibration_status_label.setText("Error")
        QMessageBox.critical(self, "Calibracion", self._device_error_message(trace))

    def calibration_thread_finished(self):
        self.calibration_start_button.setEnabled(True)
        self.calibration_stop_button.setEnabled(False)
        self.calibration_worker = None
        self.calibration_thread = None
        self.update_device_indicator()
        for page in (self.svc_page,self.mvv_page):
            page.sync()
        if self._device_requested:
            self.ensure_study_device()

    def reset_calibration(self):
        if self.calibration_worker is not None:
            self.calibration_worker.shutdown()
        self.calibration_strokes = []
        self.live_calibration_curve = []
        self.calibration_table.setRowCount(0)
        self.calibration_chart.set_curves([])
        self.calibration_result_label.setText(
            ("Pendiente de calibrar con jeringa" if spirometry._cal.get("fecha") == "pendiente" else
             f"Actual: esp {spirometry.FACTOR_ESP:.6f}    ins {spirometry.FACTOR_INS:.6f}")
        )
        self.calibration_save_button.setEnabled(False)
        self.calibration_status_label.setText("Listo")

    def refresh_calibration_table(self):
        self.calibration_table.setRowCount(len(self.calibration_strokes))
        for row, stroke in enumerate(self.calibration_strokes):
            values = [
                str(row + 1),
                stroke["direction"].upper(),
                f"{stroke['vol_modelo']:+.3f}",
                f"{stroke['pico']:.2f}",
                f"{stroke['duracion']:.2f}",
                "",
            ]
            for col, value in enumerate(values):
                self.calibration_table.setItem(row, col, QTableWidgetItem(value))
        self.calibration_chart.set_curves([stroke["curva"] for stroke in self.calibration_strokes if stroke.get("curva")])

    def _calibration_inputs(self):
        try:
            values = (
                float(self.calibration_volume_input.text().replace(",", ".")),
                float(self.calibration_temp_input.text().replace(",", ".")),
                float(self.calibration_pressure_input.text().replace(",", ".")),
                float(self.calibration_humidity_input.text().replace(",", ".")),
            )
            if not 0 < values[0] < float("inf"):
                return None
            spirometry.btps_factor(values[1], values[2], values[3])
            return values
        except ValueError:
            return None

    def refresh_calibration_result(self):
        inputs = self._calibration_inputs()
        if inputs is None:
            self.calibration_result_label.setText("Completar datos ambientales para calcular la calibracion.")
            self.calibration_save_button.setEnabled(False)
            return
        volume, temp, pressure, humidity = inputs
        pushes = [s for s in self.calibration_strokes if s["direction"] == "push"]
        pulls = [s for s in self.calibration_strokes if s["direction"] == "pull"]
        result = spirometry.calcular_resultado_calibracion(pushes, pulls, temp, pressure, humidity, volume)
        if result is None:
            self.calibration_result_label.setText(
                f"Golpes: PUSH {len(pushes)}    PULL {len(pulls)}    "
                + ("Pendiente de calibrar con jeringa" if spirometry._cal.get("fecha") == "pendiente" else
                   f"Actual: esp {spirometry.FACTOR_ESP:.6f}    ins {spirometry.FACTOR_INS:.6f}")
            )
            self.calibration_save_button.setEnabled(False)
            return
        self.calibration_result_label.setText(
            f"PUSH {len(pushes)} prom {result['prom_push']:.3f} L error {result['err_esp']:.1f}%    "
            f"PULL {len(pulls)} prom {result['prom_pull']:.3f} L error {result['err_ins']:.1f}%    "
            f"Nuevo: esp {result['factor_esp']:.6f} ins {result['factor_ins']:.6f}    "
            f"{'Dentro de tolerancia' if result['ok_ats'] else 'Fuera de tolerancia'}"
        )
        self.calibration_result_label.setStyleSheet(
            "color: #166534; font-weight: 600;" if result["ok_ats"] else "color: #b91c1c; font-weight: 600;"
        )
        self.calibration_save_button.setEnabled(len(pushes) >= 4 and len(pulls) >= 4 and result["ok_ats"])

    def save_calibration(self):
        inputs = self._calibration_inputs()
        if inputs is None:
            QMessageBox.warning(self, "Calibracion", "Completar volumen y datos ambientales.")
            return
        volume, temp, pressure, humidity = inputs
        pushes = [s for s in self.calibration_strokes if s["direction"] == "push"]
        pulls = [s for s in self.calibration_strokes if s["direction"] == "pull"]
        result = spirometry.calcular_resultado_calibracion(pushes, pulls, temp, pressure, humidity, volume)
        if result is None or len(pushes) < 4 or len(pulls) < 4:
            QMessageBox.warning(self, "Calibracion", "Se requieren al menos 4 PUSH y 4 PULL.")
            return
        if not result["ok_ats"]:
            QMessageBox.warning(
                self,
                "Calibracion",
                "Calibracion fuera de tolerancia: PUSH y PULL deben quedar dentro de +/-3%.",
            )
            return
        cal = {
            "volumen_jeringa": volume,
            "factor_esp": result["factor_esp"],
            "factor_ins": result["factor_ins"],
            "golpes_push": pushes,
            "golpes_pull": pulls,
            "temperatura_C": temp,
            "presion_mmHg": pressure,
            "humedad_pct": humidity,
            "btps_factor": round(result["btps_factor"], 4),
            "fecha": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "nota": f"calibracion GUI err_esp={result['err_esp']:.2f}%, err_ins={result['err_ins']:.2f}%",
        }
        spirometry.guardar_calibracion(cal)
        spirometry.aplicar_calibracion(cal)
        if self.calibration_worker is not None:
            self.calibration_worker.shutdown()
        self.calibration_result_label.setText(
            f"Calibracion activa: esp {spirometry.FACTOR_ESP:.6f}    ins {spirometry.FACTOR_INS:.6f}"
        )
        self.calibration_result_label.setStyleSheet("color: #166534; font-weight: 600;")
        QMessageBox.information(self, "Calibracion", "Calibracion guardada y aplicada.")

    def refresh_patients(self):
        self.patients = list(db.list_patients())
        self.filter_patients(self.patient_search_input.text() if hasattr(self, "patient_search_input") else "")

    def show_new_patient(self):
        self.editing_patient_id = None
        self.patient_form_title.setText("Nuevo paciente")
        self.save_patient_button.setText("Guardar paciente")
        self.last_name_input.clear()
        self.first_name_input.clear()
        self.dni_input.clear()
        self.birth_date_input.clear()
        self.patient_no_btps.setChecked(False)
        self.sex_input.setCurrentIndex(0)
        self.ethnicity_input.setCurrentIndex(self.ethnicity_input.findData("caucasian"))
        self.stack.setCurrentWidget(self.new_patient_page)

    def filter_patients(self, text):
        needle = text.strip().lower()
        rows = [
            patient
            for patient in self.patients
            if not needle
            or needle in (patient["first_name"] or "").lower()
            or needle in (patient["last_name"] or "").lower()
            or needle in (patient["dni"] or "").lower()
        ]
        self.patient_table.setRowCount(len(rows))
        for row, patient in enumerate(rows):
            values = [
                patient["id"],
                patient["first_name"],
                patient["last_name"],
                patient["dni"],
                self._fmt_study_datetime(patient["last_spirometry_at"]),
            ]
            for col, value in enumerate(values):
                self.patient_table.setItem(row, col, QTableWidgetItem(str(value or "")))

    def save_patient(self):
        last_name = self.last_name_input.text().strip()
        first_name = self.first_name_input.text().strip()
        dni = self.dni_input.text().strip()
        birth_date_text = self.birth_date_input.text().strip()
        birth_date_digits = "".join(char for char in birth_date_text if char.isdigit())

        if not last_name or not first_name or not dni or len(birth_date_digits) != 8:
            QMessageBox.warning(
                self,
                "Paciente",
                "Apellido, nombre, DNI y fecha de nacimiento son obligatorios.",
            )
            return
        try:
            birth_date = datetime.strptime(birth_date_text, "%d/%m/%Y").date().isoformat()
        except ValueError:
            QMessageBox.warning(self, "Paciente", "La fecha de nacimiento debe tener formato DD/MM/AAAA.")
            return
        existing_patient = db.get_patient_by_dni(dni)
        if existing_patient is not None and existing_patient["id"] != self.editing_patient_id:
            QMessageBox.warning(self, "Paciente", "Ya existe un paciente con ese DNI.")
            return
        if self.editing_patient_id is None:
            patient_id = db.create_patient(
                last_name,
                first_name,
                dni,
                birth_date,
                self.sex_input.currentData(),
                self.ethnicity_input.currentData(),
                no_btps=self.patient_no_btps.isChecked(),
            )
        else:
            patient_id = self.editing_patient_id
            db.update_patient(
                patient_id,
                last_name,
                first_name,
                dni,
                birth_date,
                self.sex_input.currentData(),
                self.ethnicity_input.currentData(),
                no_btps=self.patient_no_btps.isChecked(),
            )
            self.editing_patient_id = None
        self.current_patient_id = patient_id
        self.refresh_patients()
        self.show_patient_detail()

    def create_patient(self):
        self.save_patient()

    def open_selected_patient(self):
        row = self.patient_table.currentRow()
        if row < 0:
            return
        self.current_patient_id = int(self.patient_table.item(row, 0).text())
        self.show_patient_detail()

    def edit_selected_patient(self):
        row = self.patient_table.currentRow()
        if row < 0:
            return
        patient_id = int(self.patient_table.item(row, 0).text())
        patient = db.get_patient(patient_id)
        if patient is None:
            self.refresh_patients()
            return
        self.editing_patient_id = patient_id
        self.patient_form_title.setText("Editar paciente")
        self.save_patient_button.setText("Guardar cambios")
        self.last_name_input.setText(patient["last_name"] or "")
        self.first_name_input.setText(patient["first_name"] or "")
        self.patient_no_btps.setChecked(bool(patient['no_btps']))
        self.dni_input.setText(patient["dni"] or "")
        self.birth_date_input.setText(self._fmt_birth_date(patient["birth_date"]) if patient["birth_date"] else "")
        self.sex_input.setCurrentIndex(max(0, self.sex_input.findData(patient["sex"] or "")))
        ethnicity_index = self.ethnicity_input.findData(patient["ethnicity"] or "")
        self.ethnicity_input.setCurrentIndex(ethnicity_index if ethnicity_index >= 0 else self.ethnicity_input.findData("caucasian"))
        self.stack.setCurrentWidget(self.new_patient_page)

    def show_patient_detail(self):
        patient = db.get_patient(self.current_patient_id)
        if patient is None:
            self.show_patients()
            return
        self.patient_name_label.setText(f"{patient['first_name']} {patient['last_name']}")
        self.patient_data_label.setText(
            f"DNI: {patient['dni'] or '-'}    "
            f"Nacimiento: {self._fmt_birth_date(patient['birth_date'])}    "
            f"Sexo: {self._fmt_sex(patient['sex'])}    "
            f"Etnia GLI: {ETHNICITY_LABELS.get(patient['ethnicity'] or '', ('-', None))[0]}"
        )
        studies = db.list_sessions_for_patient(self.current_patient_id)
        self.study_table.setRowCount(len(studies))
        for row, study in enumerate(studies):
            self.study_table.setItem(row, 0, QTableWidgetItem(str(study["id"])))
            created_at = datetime.fromisoformat(study["created_at"]).strftime("%d/%m/%Y %H:%M")
            self.study_table.setItem(row, 1, QTableWidgetItem(created_at))
        if getattr(self, '_history_patient_id', None) != self.current_patient_id:
            self.patient_history_tabs.setCurrentIndex(0)
        self._history_patient_id = self.current_patient_id
        self.history_page.load(self.current_patient_id)
        self.stack.setCurrentWidget(self.patient_detail_page)

    def show_new_study(self):
        patient = db.get_patient(self.current_patient_id)
        self.study_age_label.setText(self._fmt_age(patient["birth_date"]))
        self.study_weight_input.setText("" if patient["weight_kg"] is None else str(patient["weight_kg"]))
        self.study_height_input.setText("" if patient["height_cm"] is None else str(patient["height_cm"]))
        self.stack.setCurrentWidget(self.new_study_page)

    def open_selected_study(self):
        row = self.study_table.currentRow()
        if row < 0:
            return
        self.current_session_id = int(self.study_table.item(row, 0).text())
        self.load_study(self.current_session_id)

    def start_study(self):
        try:
            environment = self.measurement_environment()
        except ValueError as exc:
            QMessageBox.warning(self, "Calibración diaria", str(exc))
            return
        try:
            weight_kg = float(self.study_weight_input.text().replace(",", "."))
            height_cm = float(self.study_height_input.text().replace(",", "."))
        except ValueError:
            QMessageBox.warning(self, "Estudio", "Peso y altura deben ser numericos.")
            return
        self.current_session_id = db.create_session(
            self.current_patient_id,
            spirometry._cal.get("fecha"),
            height_cm=height_cm,
            weight_kg=weight_kg,
        )
        db.update_patient_anthropometrics(self.current_patient_id, height_cm, weight_kg)
        self.load_study(self.current_session_id)
        self.show_calibration_notice(environment)

    def load_study(self, session_id):
        self.current_session_id = session_id
        session = db.get_session(session_id)
        if session is None:
            return
        self.current_patient_id = session["patient_id"]
        self.measurement_date_label.setText(str(session["created_at"])[:16].replace("T", " · "))
        patient = db.get_patient(self.current_patient_id)
        self.measurement_patient_label.setText(f"{patient['first_name']} {patient['last_name']}")
        self.zero_button.setToolTip(
            "Jeringa · sin corrección BTPS" if patient['no_btps'] else
            f"Paciente · ambiente de calibración diaria: {spirometry._cal.get('fecha', 'pendiente')}")
        source = json.loads(session["source_json"] or "{}")
        if source.get("origin") == "breeze":
            self.zero_button.setToolTip("Importado de Breeze · calibración original: " + str(session["calibration_date"] or "sin fecha"))
        self.measurement_patient_data_label.setText(
            f"DNI: {patient['dni'] or '-'}    "
            f"Edad: {self._fmt_age(patient['birth_date'])}    "
            + ("Referencia: " + reference_label(session))
        )
        predicted = gli2012_predicted(patient, session)
        self.predicted_values = predicted
        self.updating_maneuver_table = True
        self.maneuver_table.setRowCount(0)
        self.updating_maneuver_table = False
        self.study_curves = []
        self.study_curve_colors = []
        self.maneuver_curves = {}
        self.maneuver_volume_time_curves = {}
        self.study_volume_time_curves = []
        self.study_volume_time_colors = []
        self.maneuver_selected = {}
        self.maneuver_phase = {}
        self.set_study_phase()
        self.flow_volume_chart.set_curves([])
        self.volume_time_chart.set_curves([])
        self.flow_volume_chart.set_curve_styles([])
        self.volume_time_chart.set_curve_styles([])
        self.study_curve_colors = []
        volume = (spirometry._cal.get('volumen_jeringa') or 3.) if patient['no_btps'] else (predicted or {}).get('fvc')
        if volume is None or not math.isfinite(volume) or volume<=0:
            volume=6.
        self.flow_volume_chart.configure_study_axes(volume)
        self.volume_time_chart.configure_study_axes(volume)
        self.elapsed_label.setText("0 s")
        self.status_label.setText("Listo")
        self.add_predicted_row()
        self.add_phase_header_row("pre")
        self.add_phase_summary_row("pre")
        self.add_phase_header_row("post")
        self.add_phase_summary_row("post")
        self.load_saved_maneuvers(patient, session)
        self.refresh_visible_curves()
        self.refresh_study_summary()
        self.update_maneuver_buttons()
        self.svc_page.load()
        self.mvv_page.load()
        self.stack.setCurrentWidget(self.measurement_page)
        self._device_requested = True
        self.ensure_study_device()

    def show_summary(self):
        if self.current_session_id is None:
            return
        session = db.get_session(self.current_session_id)
        patient = db.get_patient(self.current_patient_id)
        self.summary_patient_label.setText(f"{patient['first_name']} {patient['last_name']}")
        self.summary_patient_data_label.setText(
            f"DNI: {patient['dni'] or '-'}    "
            f"Edad: {self._fmt_age(patient['birth_date'])}    "
            + ("Referencia: " + reference_label(session))
        )
        session = db.get_session(self.current_session_id)
        self.summary_report_input.blockSignals(True)
        self.summary_report_input.setPlainText(session["notes"] or "")
        self.summary_report_input.blockSignals(False)
        self.refresh_summary_page()
        self.stack.setCurrentWidget(self.summary_page)

    def save_summary_report(self):
        if self.current_session_id is None:
            return
        db.update_session_notes(self.current_session_id, self.summary_report_input.toPlainText())

    def preview_auto_report(self):
        if self.current_session_id is None:
            return
        patient = db.get_patient(self.current_patient_id)
        session = db.get_session(self.current_session_id)
        maneuvers = db.list_maneuvers_for_session(self.current_session_id)
        draft = generate_report(patient, session, maneuvers)
        if db.list_respiratory_measurements(self.current_session_id):
            draft += "\n\nEste borrador interpreta únicamente FVC. SVC y MVV requieren revisión específica del profesional."
        dialog = QDialog(self)
        dialog.setWindowTitle("Interpretación automática · borrador editable")
        dialog.resize(760, 560)
        layout = QVBoxLayout(dialog)
        note = QLabel("Revisá el borrador y las curvas. Podés editarlo antes de agregarlo al informe. "
                      "El texto que ya escribiste se conserva. Volvé a generarlo si modificás las maniobras.")
        note.setWordWrap(True)
        layout.addWidget(note)
        editor = QTextEdit()
        editor.setAcceptRichText(False)
        editor.setPlainText(draft)
        layout.addWidget(editor)
        buttons = QDialogButtonBox(QDialogButtonBox.Cancel)
        buttons.addButton("Agregar al informe", QDialogButtonBox.AcceptRole)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() == QDialog.Accepted:
            text = editor.toPlainText().strip()
            if text:
                current = self.summary_report_input.toPlainText().rstrip()
                self.summary_report_input.setPlainText((current+'\n\n' if current else '')+text)

    def preview_report(self):
        if self.current_session_id is None:
            return
        self.save_summary_report()
        self.refresh_summary_page()
        printer = QPrinter(QPrinter.HighResolution)
        printer.setPageSize(self._report_page_size())
        printer.setPageMargins(QMarginsF(0, 0, 0, 0), QPageLayout.Millimeter)
        preview = QPrintPreviewDialog(printer, self)
        preview._printer = printer
        preview.finished.connect(preview.deleteLater)
        preview.setWindowTitle("Vista previa del informe")
        preview.paintRequested.connect(self.render_report)
        preview.showMaximized()
        preview.exec()

    def render_report(self, device):
        painter = QPainter(device)
        renderer = SpirometryReportRenderer(self._report_payload())
        renderer.render(painter, QRectF(device.paperRect(QPrinter.Unit.DevicePixel)))
        painter.end()

    def export_report_pdf(self, path):
        writer = QPdfWriter(str(path))
        writer.setPageSize(self._report_page_size())
        writer.setPageMargins(QMarginsF(0, 0, 0, 0), QPageLayout.Millimeter)
        painter = QPainter(writer)
        renderer = SpirometryReportRenderer(self._report_payload())
        renderer.render(painter, QRectF(writer.pageLayout().fullRectPixels(writer.resolution())))
        painter.end()

    def save_report_pdf(self):
        if self.current_session_id is None:
            return
        self.save_summary_report()
        self.refresh_summary_page()
        patient = db.get_patient(self.current_patient_id)
        session = db.get_session(self.current_session_id)
        date_part = datetime.fromisoformat(session["created_at"]).strftime("%Y%m%d_%H%M")
        suggested = f"espirometria_{patient['dni'] or patient['id']}_{date_part}.pdf"
        dialog = file_dialog(self, "Guardar informe PDF", "PDF (*.pdf)", suggested, save=True)
        path = dialog.selectedFiles()[0] if dialog.exec() == QDialog.Accepted else ""
        dialog.deleteLater()
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        self.export_report_pdf(path)

    def _report_appearance(self):
        return {
            "header_html": self._normalize_report_header_html(
                db.get_setting("report_header_html", self._default_report_header_html())
            ),
            "header_logo_path": db.get_setting("report_logo_path", ""),
            "margin_left_mm": self._setting_int("report_margin_left_mm", 12),
            "margin_top_mm": self._setting_int("report_margin_top_mm", 6),
            "margin_right_mm": self._setting_int("report_margin_right_mm", 12),
            "margin_bottom_mm": self._setting_int("report_margin_bottom_mm", 12),
        }

    def _history_report_payload(self):
        import copy
        page=self.history_page
        patient=db.get_patient(page.patient_id) if page.patient_id is not None else None
        records=page.report_records()
        if patient is None or not records:return None
        phases=[phase for phase,check in (('pre',page.pre),('post',page.post)) if check.isChecked()]
        phase_label=' · '.join('PRE: círculos azules' if phase=='pre' else 'POST: cuadrados verdes' for phase in phases) or 'Sin fases activas'
        return {
            **self._report_appearance(),
            'title':'Tendencia espirométrica',
            'patient':dict(patient),'birth_date':self._fmt_birth_date(patient['birth_date']),
            'sex':self._fmt_sex(patient['sex']),
            'records':copy.deepcopy(records),
            'plot_records':copy.deepcopy([r for r in page.records if r['session_id'] in page.selected_studies]),
            'phases':phases,'phase_label':phase_label,
            'chart_keys':[combo.currentData() for combo in page.selectors],
            'issued_at':datetime.now().strftime('%d/%m/%Y %H:%M'),
        }

    def _configure_history_device(self,device):
        if isinstance(device,QPrinter):device.setFullPage(True)
        device.setPageSize(self._report_page_size())
        device.setPageOrientation(QPageLayout.Landscape)
        device.setPageMargins(QMarginsF(0,0,0,0),QPageLayout.Millimeter)

    def preview_history_report(self):
        payload=self._history_report_payload()
        if payload is None:return
        printer=QPrinter(QPrinter.HighResolution)
        self._configure_history_device(printer)
        preview=QPrintPreviewDialog(printer,self)
        preview._printer=printer
        preview.finished.connect(preview.deleteLater)
        preview.setWindowTitle('Imprimir tendencia')
        preview.paintRequested.connect(lambda device:self.render_history_report(device,payload))
        preview.showMaximized();preview.exec()

    def render_history_report(self,device,payload):
        from app.history_report import HistoryReportRenderer
        painter=QPainter(device)
        if not painter.isActive():raise OSError('No se pudo iniciar la impresión de la tendencia.')
        try:
            rect=QRectF(device.pageLayout().fullRectPixels(device.resolution()))
            HistoryReportRenderer(payload).render(painter,rect)
        finally:painter.end()

    def export_history_pdf(self,path,payload=None):
        payload=payload or self._history_report_payload()
        if payload is None:return False
        writer=QPdfWriter(str(path));writer.setResolution(144)
        writer.setTitle('NeumoFlow - Tendencia espirométrica');writer.setCreator('NeumoFlow')
        self._configure_history_device(writer)
        self.render_history_report(writer,payload)
        return True

    def save_history_pdf(self):
        payload=self._history_report_payload()
        if payload is None:return
        patient=payload['patient']
        suggested=f"tendencia_{patient['dni'] or patient['id']}_{datetime.now():%Y%m%d_%H%M}.pdf"
        dialog=file_dialog(self,'Guardar tendencia PDF','PDF (*.pdf)',suggested,save=True)
        path=dialog.selectedFiles()[0] if dialog.exec()==QDialog.Accepted else ''
        dialog.deleteLater()
        if not path:return
        if not path.lower().endswith('.pdf'):path+='.pdf'
        try:self.export_history_pdf(path,payload)
        except (OSError,RuntimeError) as exc:QMessageBox.warning(self,'Guardar tendencia',str(exc))

    def _report_payload(self):
        patient = db.get_patient(self.current_patient_id)
        session = db.get_session(self.current_session_id)
        charts = []
        for chart in (self.summary_flow_volume_chart, self.summary_volume_time_chart):
            # Report graphs must not inherit a short viewport from a small monitor.
            print_chart = CurveWidget(chart.mode)
            print_chart.resize(520, 420)
            print_chart.set_curves(chart.curves)
            print_chart.set_curve_styles(chart.curve_colors)
            print_chart.print_mode = True
            image = QImage(print_chart.size(), QImage.Format_ARGB32)
            image.fill(Qt.white)
            print_chart.render(image)
            charts.append(image)
        headers = [
            self.summary_table.horizontalHeaderItem(col).text()
            for col in range(self.summary_table.columnCount())
        ]
        rows = [
            [self.summary_table.item(row, col).text() for col in range(self.summary_table.columnCount())]
            for row in range(self.summary_table.rowCount())
        ]
        return {
            "title": "Informe espirometria",
            **self._report_appearance(),
            "patient": patient,
            "session": session,
            "birth_date": self._fmt_birth_date(patient["birth_date"]),
            "sex": self._fmt_sex(patient["sex"]),
            "age": self._fmt_age(patient["birth_date"]),
            "study_datetime": self._fmt_study_datetime(session["created_at"]),
            "summary_headers": headers,
            "summary_rows": rows,
            "summary_red_cells": [
                [self.fvc_red_values.isChecked() and
                 self.summary_table.item(row,col).foreground().color() == QColor('#b91c1c')
                 for col in range(self.summary_table.columnCount())]
                for row in range(self.summary_table.rowCount())
            ],
            "zscore_threshold_label": self.summary_zscore_chart.threshold_label,
            "reference_label": reference_label(session),
            "reference_note": REFERENCE_NOTE if json.loads(session["source_json"] or "{}").get("origin") == "breeze" else reference_description(session),
            "zscore_rows": self._report_zscore_rows(rows),
            "charts": charts,
            "respiratory_charts": self._respiratory_report_charts(),
            "report_text": self.summary_report_input.toPlainText(),
        }

    def _respiratory_report_charts(self):
        records=db.list_respiratory_measurements(self.current_session_id)
        result=[]
        for kind in ('svc','mvv'):
            for phase in ('pre','post'):
                candidates=[r for r in records if r['kind']==kind and r['phase']==phase and
                            r['included'] and r['result'].get(kind) is not None]
                if not candidates:continue
                record=max(candidates,key=lambda r:r['result'][kind])
                chart=CurveWidget('volume_time')
                chart.resize(1000,420)
                chart.configure_study_axes(6.,30. if kind=='svc' else 20.)
                chart.set_curve(record['result']['acq_curve']);chart.print_mode=True
                image=QImage(chart.size(),QImage.Format_ARGB32);image.fill(Qt.white);chart.render(image)
                chart.deleteLater()
                result.append({'kind':kind,'phase':phase,'image':image,'result':record['result'],
                    'reference_label':reference_label(db.get_session(self.current_session_id)),
                    'reference':reference_description(db.get_session(self.current_session_id)) or 'Sin referencia SVC/MVV configurada'})
        return result

    @staticmethod
    def _page_size_id(name):
        return {
            "A4": QPageSize.A4,
            "Legal": QPageSize.Legal,
            "Letter": QPageSize.Letter,
        }.get(name, QPageSize.A4)

    def _report_page_size(self):
        return QPageSize(self._page_size_id(db.get_setting("report_paper_size", "A4")))

    @staticmethod
    def _setting_int(key, default):
        try:
            return int(db.get_setting(key, str(default)))
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _report_zscore_rows(rows):
        wanted = {"FVC", "FEV1", "FEV1/FVC", "FEF 25-75"}
        result = []
        for row in rows:
            if row[0] not in wanted:
                continue
            result.append((row[0], MainWindow._parse_optional_float(row[4]), MainWindow._parse_optional_float(row[7])))
        return result

    @staticmethod
    def _parse_optional_float(value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _set_bold(item):
        font = QFont(item.font())
        font.setBold(True)
        item.setFont(font)

    def load_saved_maneuvers(self, patient, session):
        maneuvers = db.list_maneuvers_for_session(self.current_session_id)
        for maneuver in maneuvers:
            self._insert_saved_maneuver_row(maneuver, patient, session)
        self.set_study_phase()

    def _insert_saved_maneuver_row(self, maneuver, patient, session):
        processing = quality_processing(maneuver)
        params = {
            "fvc": maneuver["fvc"],
            "fev1": maneuver["fev1"],
            "fef2575": maneuver["fef2575"],
            "fev1_fvc": maneuver["fev1_fvc"],
            "pef": maneuver["pef"],
            "duracion": maneuver["duration"],
            "bev": maneuver["bev"],
            "meseta_eofe": bool(maneuver["eofe_ok"]),
        }
        references = gli2012_for_maneuver(patient, session, params)
        row = self._phase_summary_row(maneuver["phase"])
        self.maneuver_table.insertRow(row)
        created_at = datetime.fromisoformat(maneuver["created_at"]).strftime("%H:%M:%S")
        values = [
            str(maneuver["id"]),
            created_at,
            "",
            "-",
            self._fmt_metric(maneuver["fvc"]),
            self._fmt_reference(references, "fvc", "percent"),
            self._fmt_reference(references, "fvc", "zscore"),
            self._fmt_metric(maneuver["fev1"]),
            self._fmt_reference(references, "fev1", "percent"),
            self._fmt_reference(references, "fev1", "zscore"),
            "-" if maneuver["fev1_fvc"] is None else f"{maneuver['fev1_fvc']*100:.1f}%",
            self._fmt_reference(references, "fev1_fvc", "zscore"),
            self._fmt_metric(maneuver["fef2575"]),
            self._fmt_reference(references, "fef2575", "percent"),
            self._fmt_reference(references, "fef2575", "zscore"),
            self._fmt_metric(maneuver["pef"]),
            self._fmt_metric(maneuver["duration"]),
            quality_text(processing) if processing.get("quality_version") else self._fmt_quality(self._quality_errors_from_row(maneuver)),
        ]
        self.updating_maneuver_table = True
        for col, value in enumerate(values):
            item = QTableWidgetItem(value)
            if col == 2:
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setToolTip('Incluir la maniobra. Los parámetros afectados por alertas de calidad requieren revisión por separado.')
                item.setCheckState(Qt.Checked if maneuver["review_status"] == "accepted" else Qt.Unchecked)
            if col == 3:
                item.setText("")
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Checked if maneuver["print_selected"] else Qt.Unchecked)
            if col in {4, 7, 10}:
                self._set_bold(item)
            item.setTextAlignment(Qt.AlignCenter)
            if col == 17 and self._row_is_maneuver(row):
                item.setToolTip(value + '\nEvaluación orientativa: requiere revisión visual del operador.')
            self.maneuver_table.setItem(row, col, item)
        self.updating_maneuver_table = False
        # Persisted tuples do not retain cached flow or filter history. Reuse
        # the recorded curve instead of applying a different model on reopen.
        self.maneuver_volume_time_curves[maneuver["id"]]=volume_time_curve(processing)
        curve = processing.get("acq_curve") or processing.get("vol_curve") or []
        if curve:
            self.maneuver_curves[maneuver["id"]] = curve
        self.maneuver_selected[maneuver["id"]] = maneuver["review_status"] == "accepted"
        self.maneuver_phase[maneuver["id"]] = maneuver["phase"]
        self.refresh_curve_row_colors()
        self.refresh_visible_curves()

    def toggle_maneuver(self):
        if self.capture_active and self.worker is not None:
            self.worker.stop()
            self.maneuver_button.setEnabled(False)
            self.status_label.setText("Finalizando")
            return
        self.start_maneuver()

    def space_maneuver(self):
        if self.stack.currentWidget() == self.measurement_page and self.maneuver_button.isEnabled():
            self.maneuver_button.click()

    def additional_effort_marked(self, marker_time):
        if self._capture_page is not None:
            self._capture_page.mark_time=marker_time

    def open_additional_measurement(self, page):
        if self.capture_active:return
        page.load()
        self.stack.setCurrentWidget(page)

    def lock_capture_navigation(self, locked):
        self.phase_selector.setEnabled(not locked)
        for button in (self.measurement_tab,self.svc_tab,self.mvv_tab,self.measurement_summary_tab,
                       self.patients_button,self.new_patient_button,self.settings_button,self.calibration_button,self.study_button):
            button.setEnabled(not locked)
        for page in (self.svc_page,self.mvv_page):page.sync()

    def start_additional_capture(self, page):
        if self.capture_active:return
        self.set_study_phase(page.phase.currentData())
        if self.worker is None or not self.device_ready:
            self._device_requested=True
            self.ensure_study_device()
            return
        try:
            environment=self.measurement_environment()
        except ValueError as exc:
            QMessageBox.warning(self,"Condiciones de medición",str(exc));return
        self.show_calibration_notice(environment)
        self._capture_page=page
        self.capture_active=True
        self.maneuver_started_at=None
        self.lock_capture_navigation(True)
        page.marked=False;page.mark_time=None;page.baseline_cued=False;page.plateau_cued=False
        page.live_curve=[];page.chart.set_curves([])
        page.sync()
        self.worker.start_capture(environment,mode=page.kind,
            direction=page.option.currentData() if page.kind=='svc' else 'evc',
            target_seconds=page.option.currentData() if page.kind=='mvv' else 12)

    def measurement_environment(self):
        patient = db.get_patient(self.current_patient_id)
        if patient is None:
            raise ValueError("Seleccioná una ficha de paciente")
        return spirometry.ambiente_desde_calibracion(bool(patient['no_btps']))

    def show_calibration_notice(self, environment):
        notice = environment.get('calibration_notice')
        key = (self.current_session_id, environment.get('calibration_date'))
        if notice and key != self._calibration_notice_key:
            QMessageBox.warning(self, "Calibración diaria recomendada", notice, QMessageBox.Ok)
            self._calibration_notice_key = key

    def study_screen_changed(self, *_args):
        self.maneuver_space_shortcut.setEnabled(self.stack.currentWidget() == self.measurement_page)
        self._device_requested = (self.stack.currentWidget() in (self.measurement_page,self.svc_page,self.mvv_page)
                                  and self.current_session_id is not None)
        if self._device_requested:
            self.ensure_study_device()
        elif self.worker is not None:
            self.device_ready = False
            self.worker.shutdown()

    def ensure_study_device(self):
        if not self._device_requested:
            return
        if self.calibration_worker is not None:
            self.maneuver_button.setEnabled(False)
            self.status_label.setText("Finalizá la calibración antes de preparar el estudio")
            return
        if self.worker is not None:
            if self._device_study_id != self.current_session_id:
                self.device_ready = False
                self.worker.shutdown()
            return
        self.device_ready = False
        self.maneuver_button.setEnabled(False)
        self.zero_button.setEnabled(False)
        self.status_label.setText("Puesta a cero: mantené el sensor en reposo")
        self._device_study_id = self.current_session_id
        self.thread = QThread()
        self.worker = StudySessionWorker()
        worker = self.worker
        worker.moveToThread(self.thread)
        self.thread.started.connect(worker.run)
        worker.status.connect(self.status_label.setText)
        worker.status.connect(self.svc_page.status.setText)
        worker.status.connect(self.mvv_page.status.setText)
        worker.ready.connect(self.study_device_ready)
        worker.capture_started.connect(self.maneuver_detected)
        worker.effort_marked.connect(self.additional_effort_marked)
        worker.progress.connect(self.update_live_curve)
        worker.finished.connect(self.study_capture_finished)
        worker.capture_closed.connect(self.capture_closed)
        worker.failed.connect(self.study_device_failed)
        worker.closed.connect(self.thread.quit, Qt.DirectConnection)
        worker.closed.connect(worker.deleteLater)
        self.thread.finished.connect(self.measurement_thread_finished)
        self.update_device_indicator()
        self.thread.start()

    def study_device_ready(self):
        if not self._device_requested or self._device_study_id != self.current_session_id:
            return
        self.device_ready = True
        self.maneuver_button.setEnabled(True)
        self.zero_button.setEnabled(True)
        for page in (self.svc_page,self.mvv_page):page.sync()
        self.update_device_indicator()

    def repeat_zero(self):
        if self.capture_active:
            return
        self._device_requested = True
        if self.worker is None:
            self.ensure_study_device()
            return
        self.device_ready = False
        self.maneuver_button.setEnabled(False)
        self.zero_button.setEnabled(False)
        self.status_label.setText("Puesta a cero: mantené el sensor en reposo")
        self.update_device_indicator()
        for page in (self.svc_page,self.mvv_page):page.sync()
        self.worker.zero()

    def study_device_failed(self, trace):
        self._device_requested = False
        self.device_ready = False
        self.measurement_failed(trace)

    def study_capture_finished(self, samples, params):
        if self._device_requested and self._device_study_id == self.current_session_id:
            if self._capture_page is not None:
                page=self._capture_page
                db.save_respiratory_measurement(self.current_session_id,page.kind,page.phase.currentData(),params,samples)
                page.load()
                page.status.setText('Medición guardada; revisá la curva antes de incluirla.')
                self.refresh_summary_page()
            else:
                self.measurement_finished(samples, params)

    def capture_closed(self):
        self.capture_active = False
        self._capture_page = None
        self.lock_capture_navigation(False)
        for page in (self.svc_page,self.mvv_page):page.sync()
        self.elapsed_timer.stop()
        self.update_elapsed_time()
        self.maneuver_button.setText("Iniciar maniobra")
        self.maneuver_button.setProperty("recording", False)
        repolish(self.maneuver_button)
        set_button_icon(self.maneuver_button, QStyle.SP_MediaPlay)
        self.maneuver_button.setEnabled(self.device_ready)
        self.zero_button.setEnabled(self.device_ready)

    def start_maneuver(self):
        if self.capture_active:
            return
        self.set_study_phase(self.current_phase)
        if self.worker is None or not self.device_ready:
            self._device_requested = True
            self.ensure_study_device()
            return
        try:
            environment = self.measurement_environment()
        except ValueError as exc:
            QMessageBox.warning(self, "Condiciones de medición", str(exc))
            return
        self.show_calibration_notice(environment)
        self.current_samples = None
        self.current_params = None
        self.flow_volume_chart.set_curves(self.study_curves)
        self.volume_time_chart.set_curves(self.study_volume_time_curves)
        self.maneuver_started_at = None
        self.elapsed_label.setText("0 s")
        self.capture_active = True
        self._capture_page = None
        self.lock_capture_navigation(True)
        self.zero_button.setEnabled(False)
        self.maneuver_button.setText("Finalizar maniobra")
        self.maneuver_button.setProperty("recording", True)
        repolish(self.maneuver_button)
        set_button_icon(self.maneuver_button, QStyle.SP_MediaStop)
        self.status_label.setText("Iniciando captura")
        self.flow_volume_chart.set_quality_regions([])
        self.volume_time_chart.set_quality_regions([])
        self.zero_button.setToolTip(spirometry.descripcion_ambiente(environment) +
            (f" · calibración {environment['calibration_date']}" if 'calibration_date' in environment else ""))
        self.worker.start_capture(environment)

    def update_elapsed_time(self):
        if self.maneuver_started_at is None:
            return
        elapsed = int(time.monotonic() - self.maneuver_started_at)
        self.elapsed_label.setText(f"{elapsed} s")

    def maneuver_detected(self):
        if self.capture_active and self.maneuver_started_at is None:
            self.maneuver_started_at = time.monotonic()
            self.elapsed_label.setText("0 s")
            self.elapsed_timer.start(250)

    def update_live_curve(self, vol_curve):
        if self._capture_page is not None:
            self._capture_page.progress(vol_curve)
            return
        if self.current_params is None:
            curves = [*self.study_curves, vol_curve]
            live_color=CURVE_COLORS[len(self.maneuver_phase) % len(CURVE_COLORS)]
            self.flow_volume_chart.set_curve_styles([*self.study_curve_colors,live_color],len(curves)-1)
            self.flow_volume_chart.set_curves(curves)
            # The active acquisition still displays preparation/flat zero in real time.
            volume_curves=[*self.study_volume_time_curves,vol_curve]
            self.volume_time_chart.set_curve_styles([*self.study_volume_time_colors,live_color],len(volume_curves)-1)
            self.volume_time_chart.set_curves(volume_curves)

    def measurement_finished(self, samples, params):
        self.current_samples = samples
        self.current_params = params
        if not params:
            self.status_label.setText("No se detecto maniobra")
            return

        maneuver_id = db.save_maneuver(
            self.current_session_id,
            params,
            samples,
            review_status="accepted",
            phase=self.current_phase,
        )
        patient = db.get_patient(self.current_patient_id)
        session = db.get_session(self.current_session_id)
        references = gli2012_for_maneuver(patient, session, params)
        created_at = time.strftime("%H:%M:%S")
        row = self._phase_summary_row(self.current_phase)
        self.maneuver_table.insertRow(row)
        values = [
            str(maneuver_id),
            created_at,
            "",
            "-",
            self._fmt_metric(params.get("fvc")),
            self._fmt_reference(references, "fvc", "percent"),
            self._fmt_reference(references, "fvc", "zscore"),
            self._fmt_metric(params.get("fev1")),
            self._fmt_reference(references, "fev1", "percent"),
            self._fmt_reference(references, "fev1", "zscore"),
            "-" if params.get("fev1_fvc") is None else f"{params['fev1_fvc']*100:.1f}%",
            self._fmt_reference(references, "fev1_fvc", "zscore"),
            self._fmt_metric(params.get("fef2575")),
            self._fmt_reference(references, "fef2575", "percent"),
            self._fmt_reference(references, "fef2575", "zscore"),
            self._fmt_metric(params.get("pef")),
            self._fmt_metric(params.get("duracion")),
            quality_text(params),
        ]
        self.updating_maneuver_table = True
        for col, value in enumerate(values):
            item = QTableWidgetItem(value)
            if col == 2:
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Checked)
                item.setToolTip('Incluir la maniobra. Los parámetros afectados por alertas de calidad requieren revisión por separado.')
            if col == 3:
                item.setText("")
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Unchecked)
            if col in {4, 7, 10}:
                self._set_bold(item)
            item.setTextAlignment(Qt.AlignCenter)
            if col == 17 and self._row_is_maneuver(row):
                item.setToolTip(value + '\nEvaluación orientativa: requiere revisión visual del operador.')
            self.maneuver_table.setItem(row, col, item)
        self.updating_maneuver_table = False
        self.maneuver_table.selectRow(row)
        display_curve = params.get("acq_curve") or params["vol_curve"]
        self.maneuver_curves[maneuver_id] = display_curve
        self.maneuver_volume_time_curves[maneuver_id] = volume_time_curve(params)
        self.maneuver_selected[maneuver_id] = True
        self.maneuver_phase[maneuver_id] = self.current_phase
        self.refresh_curve_row_colors()
        self.refresh_visible_curves()
        mode = params.get('environment', {}).get('mode')
        self.status_label.setText("Maniobra guardada · " + (
            "paciente, corrección ambiental CPFS" if mode == 'patient' else "jeringa, sin corrección BTPS"))
        self.refresh_study_summary(notify=True)
        self.update_maneuver_buttons()

    def delete_excluded_maneuvers(self):
        rows_to_delete = [
            row
            for row in range(self.maneuver_table.rowCount())
            if self._row_is_maneuver(row) and self.maneuver_table.item(row, 2).checkState() != Qt.Checked
        ]
        if not rows_to_delete:
            return
        answer = QMessageBox.question(
            self,
            "Borrar maniobras",
            "Desea borrar todas las maniobras no seleccionadas?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        deleted = db.delete_excluded_maneuvers(self.current_session_id)
        for row in reversed(rows_to_delete):
            maneuver_id = int(self.maneuver_table.item(row, 0).text())
            self.maneuver_curves.pop(maneuver_id, None)
            self.maneuver_volume_time_curves.pop(maneuver_id, None)
            self.maneuver_selected.pop(maneuver_id, None)
            self.maneuver_phase.pop(maneuver_id, None)
            self.maneuver_table.removeRow(row)
        self.refresh_curve_row_colors()
        self.refresh_visible_curves()
        self.status_label.setText(f"Maniobras borradas: {deleted}")
        self.refresh_study_summary()
        self.update_maneuver_buttons()

    def maneuver_item_changed(self, item):
        if self.updating_maneuver_table or item.column() not in {2, 3}:
            return
        row = item.row()
        if not self._row_is_maneuver(row):
            return
        maneuver_id = int(self.maneuver_table.item(row, 0).text())
        if item.column() == 2:
            include = item.checkState() == Qt.Checked
            db.update_maneuver_status(maneuver_id, "accepted" if include else "excluded")
            self.maneuver_selected[maneuver_id] = include
            self.status_label.setText("Maniobra incluida" if include else "Maniobra excluida")
            if not include and self.maneuver_table.item(row, 3).checkState() == Qt.Checked:
                self._set_print_row(None, self._phase_for_row(row))
            self.refresh_visible_curves()
        else:
            if item.checkState() == Qt.Checked:
                self._set_print_row(row, self._phase_for_row(row))
            else:
                self._set_print_row(None, self._phase_for_row(row))
        self.refresh_study_summary()
        self.update_maneuver_buttons()

    def phase_changed(self, *_args):
        self.set_study_phase(self.phase_selector.currentData())

    def set_study_phase(self, phase=None):
        if self.current_session_id is None:return
        if self.capture_active:phase=self.current_phase
        locked=db.post_phase_started(self.current_session_id)
        if phase=='post' or locked:
            db.begin_post_phase(self.current_session_id)
            phase='post';locked=True
        else:phase='pre'
        self.current_phase=phase
        tip='Etapa POST iniciada: no se pueden registrar nuevas maniobras PRE.' if locked else ''
        with QSignalBlocker(self.phase_selector):
            self.phase_selector.setItemEnabled(self.phase_selector.findData('pre'),not locked)
            self.phase_selector.setItemToolTip(self.phase_selector.findData('pre'),tip)
            self.phase_selector.setCurrentIndex(self.phase_selector.findData(phase))
        for page in (self.svc_page,self.mvv_page):
            with QSignalBlocker(page.phase):
                page.phase.model().item(page.phase.findData('pre')).setEnabled(not locked)
                page.phase.setItemData(page.phase.findData('pre'),tip,Qt.ToolTipRole)
                page.phase.setCurrentIndex(page.phase.findData(phase))
        self.status_label.setText(f"Fase {self.current_phase.upper()}")
        self.apply_maneuver_table_view()
        self.update_session_feedback()

    def update_maneuver_buttons(self):
        has_excluded = any(
            self._row_is_maneuver(r) and self.maneuver_table.item(r, 2).checkState() != Qt.Checked
            for r in range(self.maneuver_table.rowCount())
        )
        if hasattr(self, "delete_button"):
            self.delete_button.setEnabled(has_excluded)

    def maneuver_colors(self):
        # Curve identity/colors follow acquisition order, independently of table ranking.
        ids = list(self.maneuver_phase)
        return {key: CURVE_COLORS[i % len(CURVE_COLORS)] for i, key in enumerate(ids)}

    def refresh_curve_row_colors(self):
        colors = self.maneuver_colors()
        for row in range(self.maneuver_table.rowCount()):
            if self._row_is_maneuver(row):
                key = int(self.maneuver_table.item(row, 0).text())
                swatch = QPixmap(10, 10)
                swatch.fill(Qt.transparent)
                painter = QPainter(swatch)
                painter.setRenderHint(QPainter.Antialiasing)
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(colors[key]))
                painter.drawEllipse(1, 1, 8, 8)
                painter.end()
                self.maneuver_table.item(row, 1).setIcon(QIcon(swatch))

    def refresh_visible_curves(self):
        ids = [key for key in self.maneuver_curves if self.maneuver_selected.get(key, False)]
        selected_row = self.maneuver_table.currentRow()
        selected_id = int(self.maneuver_table.item(selected_row, 0).text()) if self._row_is_maneuver(selected_row) else None
        if selected_id in self.maneuver_curves and selected_id not in ids:
            ids.append(selected_id)
        self.study_curves = [self.maneuver_curves[key] for key in ids]
        colors = self.maneuver_colors()
        self.study_curve_colors = [colors[key] for key in ids]
        row = self.maneuver_table.currentRow()
        selected = int(self.maneuver_table.item(row, 0).text()) if self._row_is_maneuver(row) else None
        highlight = ids.index(selected) if selected in ids else None
        counts = {"pre": 0, "post": 0}
        names = {}
        for key in colors:
            phase = self.maneuver_phase.get(key, "pre")
            counts[phase] += 1
            names[key] = f"{phase.upper()} {counts[phase]}"
        entries = [f'<span style="color:{colors[key]}">━</span> {names[key]}' +
                   (" · seleccionada" if key == selected else "") for key in ids]
        self.curve_legend_label.setText(" &nbsp; &nbsp; ".join(entries[:6]) +
            (f" &nbsp; +{len(entries)-6} curvas" if len(entries) > 6 else ""))
        self.curve_legend_label.setToolTip(" · ".join(names[key] for key in ids))
        self.curve_legend_label.setVisible(bool(entries))
        self.flow_volume_chart.set_curve_styles(self.study_curve_colors,highlight)
        self.flow_volume_chart.set_curves(self.study_curves)
        volume_ids=[key for key in ids if self.maneuver_volume_time_curves.get(key)]
        self.study_volume_time_curves=[self.maneuver_volume_time_curves[key] for key in volume_ids]
        self.study_volume_time_colors=[colors[key] for key in volume_ids]
        self.volume_time_chart.set_curve_styles(self.study_volume_time_colors,volume_ids.index(selected) if selected in volume_ids else None)
        self.volume_time_chart.set_curves(self.study_volume_time_curves)
        record = next((m for m in db.list_maneuvers_for_session(self.current_session_id) if m['id'] == selected), None) if selected else None
        params = quality_processing(record) if record else {}
        self.flow_volume_chart.set_quality_regions(plot_regions(params, acquisition=True))
        self.volume_time_chart.set_quality_regions(plot_regions(params))

    def add_predicted_row(self):
        row = self.maneuver_table.rowCount()
        self.maneuver_table.insertRow(row)
        predicted = self.predicted_values or {}
        references = gli2012_for_maneuver(
            db.get_patient(self.current_patient_id), db.get_session(self.current_session_id), predicted)
        values = [
            "",
            "Predicho",
            "",
            "",
            self._fmt_metric(predicted.get("fvc")),
            "-",
            self._fmt_reference(references, "fvc", "zscore"),
            self._fmt_metric(predicted.get("fev1")),
            "-",
            self._fmt_reference(references, "fev1", "zscore"),
            "-" if predicted.get("fev1_fvc") is None else f"{predicted['fev1_fvc']*100:.1f}%",
            self._fmt_reference(references, "fev1_fvc", "zscore"),
            self._fmt_metric(predicted.get("fef2575")),
            "-",
            self._fmt_reference(references, "fef2575", "zscore"),
            "-",
            "-",
            "-",
        ]
        self.updating_maneuver_table = True
        for col, value in enumerate(values):
            item = QTableWidgetItem(value)
            item.setBackground(QColor("#fff7d6"))
            if col in {1, 4, 7, 10}:
                self._set_bold(item)
            item.setTextAlignment(Qt.AlignCenter)
            if col == 17 and self._row_is_maneuver(row):
                item.setToolTip(value + '\nEvaluación orientativa: requiere revisión visual del operador.')
            self.maneuver_table.setItem(row, col, item)
        self.updating_maneuver_table = False

    def add_phase_header_row(self, phase):
        row = self.maneuver_table.rowCount()
        self.maneuver_table.insertRow(row)
        values = ["", phase.upper(), "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", ""]
        self.updating_maneuver_table = True
        for col, value in enumerate(values):
            item = QTableWidgetItem(value)
            item.setBackground(QColor("#e1f1ef"))
            item.setTextAlignment(Qt.AlignCenter)
            if col == 17 and self._row_is_maneuver(row):
                item.setToolTip(value + '\nEvaluación orientativa: requiere revisión visual del operador.')
            self.maneuver_table.setItem(row, col, item)
        self.updating_maneuver_table = False

    def add_phase_summary_row(self, phase):
        row = self.maneuver_table.rowCount()
        self.maneuver_table.insertRow(row)
        label = "ATS" if phase == "pre" else "Compuesto"
        values = ["", label, "", "", "-", "-", "-", "-", "-", "-", "-", "-", "-", "-", "-", "-", "-", "-"]
        self.updating_maneuver_table = True
        for col, value in enumerate(values):
            item = QTableWidgetItem(value)
            item.setBackground(QColor("#e5e7eb"))
            if col in {1, 4, 7, 10}:
                self._set_bold(item)
            item.setToolTip("Resumen de mejores valores incluidos en " + phase.upper())
            item.setTextAlignment(Qt.AlignCenter)
            if col == 17 and self._row_is_maneuver(row):
                item.setToolTip(value + '\nEvaluación orientativa: requiere revisión visual del operador.')
            self.maneuver_table.setItem(row, col, item)
        self.updating_maneuver_table = False

    def _row_is_maneuver(self, row):
        item = self.maneuver_table.item(row, 0)
        return item is not None and bool(item.text())

    def _phase_summary_row(self, phase):
        label = "ATS" if phase == "pre" else "Compuesto"
        for row in range(self.maneuver_table.rowCount()):
            label_item = self.maneuver_table.item(row, 1)
            if label_item and label_item.text() == label:
                return row
        return self.maneuver_table.rowCount()

    def refresh_study_summary(self, notify=False):
        if self.current_session_id is None:
            return
        maneuvers = db.list_maneuvers_for_session(self.current_session_id)
        maneuvers_by_id = {m["id"]: m for m in maneuvers}
        self.rank_maneuver_rows(maneuvers_by_id)
        patient = db.get_patient(self.current_patient_id)
        session = db.get_session(self.current_session_id)
        accepted = [m for m in maneuvers if m["review_status"] == "accepted"]
        accepted_pre = [m for m in accepted if m["phase"] == "pre"]
        accepted_post = [m for m in accepted if m["phase"] == "post"]
        pre_summary = self._phase_summary("PRE", accepted_pre)
        post_summary = self._phase_summary("POST", accepted_post)
        parts = [pre_summary, post_summary]

        best_pre_fvc = self._best_metric(accepted_pre, "fvc")
        best_pre_fev1 = self._best_metric(accepted_pre, "fev1")
        best_pre_fef2575 = self._best_metric(accepted_pre, "fef2575")
        best_pre_pef = self._best_metric(accepted_pre, "pef")
        best_post_fvc = self._best_metric(accepted_post, "fvc")
        best_post_fev1 = self._best_metric(accepted_post, "fev1")
        best_post_fef2575 = self._best_metric(accepted_post, "fef2575")
        best_post_pef = self._best_metric(accepted_post, "pef")
        if best_pre_fvc and best_post_fvc:
            parts.append(f"Cambio FVC {self._percent_change(best_pre_fvc['fvc'], best_post_fvc['fvc']):+.1f}%")
        if best_pre_fev1 and best_post_fev1:
            parts.append(f"Cambio FEV1 {self._percent_change(best_pre_fev1['fev1'], best_post_fev1['fev1']):+.1f}%")
        if best_pre_fef2575 and best_post_fef2575:
            parts.append(f"Cambio FEF25-75 {self._percent_change(best_pre_fef2575['fef2575'], best_post_fef2575['fef2575']):+.1f}%")

        best_ids = {
            ("pre", "fvc"): best_pre_fvc["id"] if best_pre_fvc else None,
            ("pre", "fev1"): best_pre_fev1["id"] if best_pre_fev1 else None,
            ("post", "fvc"): best_post_fvc["id"] if best_post_fvc else None,
            ("post", "fev1"): best_post_fev1["id"] if best_post_fev1 else None,
        }
        for row in range(self.maneuver_table.rowCount()):
            if not self._row_is_maneuver(row):
                continue
            maneuver_id = int(self.maneuver_table.item(row, 0).text())
            phase = maneuvers_by_id[maneuver_id]["phase"]
            if phase == "post":
                fvc_item = self.maneuver_table.item(row, 5)
                fev1_item = self.maneuver_table.item(row, 8)
                fef_item = self.maneuver_table.item(row, 13)
                maneuver = maneuvers_by_id[maneuver_id]
                fvc = maneuver["fvc"]
                fev1 = maneuver["fev1"]
                fef2575 = maneuver["fef2575"]
                fvc_percent = self._metric_percent_of_predicted(maneuver, "fvc")
                fev1_percent = self._metric_percent_of_predicted(maneuver, "fev1")
                fef_percent = self._metric_percent_of_predicted(maneuver, "fef2575")
                fvc_item.setText(
                    "-" if not best_pre_fvc or fvc is None else f"{fvc_percent} ({self._percent_change(best_pre_fvc['fvc'], fvc):+.1f})"
                )
                fev1_item.setText(
                    "-" if not best_pre_fev1 or fev1 is None else f"{fev1_percent} ({self._percent_change(best_pre_fev1['fev1'], fev1):+.1f})"
                )
                fef_item.setText(
                    "-" if not best_pre_fef2575 or fef2575 is None else f"{fef_percent} ({self._percent_change(best_pre_fef2575['fef2575'], fef2575):+.1f})"
                )
            else:
                maneuver = maneuvers_by_id[maneuver_id]
                self.maneuver_table.item(row, 5).setText(self._metric_percent_of_predicted(maneuver, "fvc"))
                self.maneuver_table.item(row, 8).setText(self._metric_percent_of_predicted(maneuver, "fev1"))
                self.maneuver_table.item(row, 13).setText(self._metric_percent_of_predicted(maneuver, "fef2575"))

            references = gli2012_for_maneuver(patient, session, dict(maneuver))
            self._color_reference_cells(self.maneuver_table, row, dict(maneuver), references,
                {'fvc':(4,5,6), 'fev1':(7,8,9), 'fev1_fvc':(10,11), 'fef2575':(12,13,14)})
            params = quality_processing(maneuver)
            if params.get('quality_version') == 1:
                states = quality_assessment(params)
                for metric, columns in (('fvc', (4,5,6)), ('fev1', (7,8,9))):
                    state = states[metric]
                    note = metric.upper()+': '+QUALITY_STATES[state['state']]
                    if state['reasons']:
                        note += '. '+'; '.join(state['reasons'])+'. No aporta al sumario hasta resolver la calidad.'
                    for column in columns:
                        item = self.maneuver_table.item(row, column)
                        item.setToolTip((item.toolTip()+'\n'+note).strip())

        self._ensure_print_selection(best_ids, maneuvers_by_id)

        self._update_phase_summary_row("pre", best_pre_fvc, best_pre_fev1, best_pre_fef2575, best_pre_pef, None, None, None)
        self._update_phase_summary_row("post", best_post_fvc, best_post_fev1, best_post_fef2575, best_post_pef, best_pre_fvc, best_pre_fev1, best_pre_fef2575)
        self.refresh_summary_page()
        self.apply_maneuver_table_view()
        self.update_session_feedback(maneuvers, notify=notify)

    def update_session_feedback(self, maneuvers=None, notify=False):
        if self.current_session_id is None:
            return
        from app.session_quality import session_feedback
        from app.reference_values import age_years
        patient = db.get_patient(self.current_patient_id)
        session = db.get_session(self.current_session_id)
        try:
            age = age_years(patient['birth_date'], datetime.fromisoformat(session['created_at']).date())
        except (ValueError, TypeError):
            age = None
        maneuvers = maneuvers if maneuvers is not None else db.list_maneuvers_for_session(self.current_session_id)
        result = session_feedback(maneuvers, self.current_phase, age)
        key = (self.current_session_id, self.current_phase)
        previous = self._last_quality_ready.get(key, False)
        self._last_quality_ready[key] = result['ready']
        self.session_quality_label.setText(result['text'])
        self.session_quality_label.setToolTip(result['tooltip'])
        self.session_quality_label.setProperty('state', result['state'])
        repolish(self.session_quality_label)
        if notify and result['ready'] and not previous:
            QApplication.beep()

    def rank_maneuver_rows(self, maneuvers_by_id):
        """Order only the maneuver rows in each phase by descending FVC + FEV1."""
        table=self.maneuver_table
        current=table.currentRow()
        selected=int(table.item(current,0).text()) if self._row_is_maneuver(current) else None
        changed=False
        def score(row):
            maneuver=maneuvers_by_id[int(table.item(row,0).text())]
            values=(maneuver['fvc'],maneuver['fev1'])
            return sum(values) if all(value is not None and math.isfinite(value) for value in values) else -math.inf
        with QSignalBlocker(table):
            for phase in ('pre','post'):
                rows=[row for row in range(table.rowCount()) if self._row_is_maneuver(row) and self._phase_for_row(row)==phase]
                ranked=sorted(rows,key=score,reverse=True)
                if rows==ranked:continue
                cells=[[table.takeItem(row,column) for column in range(table.columnCount())] for row in ranked]
                for row,items in zip(rows,cells):
                    for column,item in enumerate(items):table.setItem(row,column,item)
                changed=True
            if changed and selected is not None:
                table.selectRow(self._row_for_maneuver(selected))
        if changed:
            self.refresh_visible_curves()

    @staticmethod
    def _best_metric(maneuvers, key):
        valid = [m for m in maneuvers if m[key] is not None and metric_eligible(m, key)]
        return max(valid, key=lambda m: m[key]) if valid else None

    def _phase_summary(self, label, maneuvers):
        fvc_values = sorted((m["fvc"] for m in maneuvers if m["fvc"] is not None and metric_eligible(m, "fvc")), reverse=True)
        fev1_values = sorted((m["fev1"] for m in maneuvers if m["fev1"] is not None and metric_eligible(m, "fev1")), reverse=True)
        parts = [f"{label}: {len(maneuvers)} sel."]
        if fvc_values:
            parts.append(f"FVC {fvc_values[0]:.2f} L")
        if fev1_values:
            parts.append(f"FEV1 {fev1_values[0]:.2f} L")
        if len(fvc_values) >= 2 and len(fev1_values) >= 2:
            fvc_diff = fvc_values[0] - fvc_values[1]
            fev1_diff = fev1_values[0] - fev1_values[1]
            parts.append(f"rep {'OK' if fvc_diff <= 0.150 and fev1_diff <= 0.150 else 'repetir'}")
        return " ".join(parts)

    @staticmethod
    def _percent_change(baseline, value):
        return ((value - baseline) / baseline) * 100 if baseline else 0.0

    def _update_phase_summary_row(self, phase, best_fvc, best_fev1, best_fef2575, best_pef, baseline_fvc, baseline_fev1, baseline_fef2575):
        row = self._phase_summary_row(phase)
        if row >= self.maneuver_table.rowCount():
            return
        best_ratio = None
        if best_fvc and best_fev1 and best_fvc["fvc"]:
            best_ratio = best_fev1["fev1"] / best_fvc["fvc"]
        fvc_z = self._summary_zscore(best_fvc, "fvc")
        fev1_z = self._summary_zscore(best_fev1, "fev1")
        fef2575_z = self._summary_zscore(best_fef2575, "fef2575")
        values = {
            4: self._fmt_metric(best_fvc["fvc"] if best_fvc else None),
            5: self._summary_percent(best_fvc, baseline_fvc, "fvc"),
            6: fvc_z,
            7: self._fmt_metric(best_fev1["fev1"] if best_fev1 else None),
            8: self._summary_percent(best_fev1, baseline_fev1, "fev1"),
            9: fev1_z,
            10: "-" if best_ratio is None else f"{best_ratio*100:.1f}%",
            12: self._fmt_metric(best_fef2575["fef2575"] if best_fef2575 else None),
            13: self._summary_percent(best_fef2575, baseline_fef2575, "fef2575"),
            14: fef2575_z,
            15: self._fmt_metric(best_pef["pef"] if best_pef else None),
        }
        for col, value in values.items():
            self.maneuver_table.item(row, col).setText(value)
        parameters = {'fvc':best_fvc['fvc'] if best_fvc else None,
                      'fev1':best_fev1['fev1'] if best_fev1 else None,
                      'fev1_fvc':best_ratio,
                      'fef2575':best_fef2575['fef2575'] if best_fef2575 else None}
        references = gli2012_for_maneuver(db.get_patient(self.current_patient_id),
                                         db.get_session(self.current_session_id), parameters)
        self._color_reference_cells(self.maneuver_table, row, parameters, references,
            {'fvc':(4,5,6), 'fev1':(7,8,9), 'fev1_fvc':(10,11), 'fef2575':(12,13,14)})

    def _summary_percent(self, maneuver, baseline, key):
        if not maneuver:
            return "-"
        predicted_percent = self._metric_percent_of_predicted(maneuver, key)
        if not baseline:
            return predicted_percent
        change = self._percent_change(baseline[key], maneuver[key])
        return f"{predicted_percent} ({change:+.1f})"

    def _metric_percent_of_predicted(self, maneuver, key):
        predicted = (self.predicted_values or {}).get(key)
        if not predicted or maneuver[key] is None:
            return "-"
        return f"{(maneuver[key] / predicted) * 100:.1f}"

    def _ensure_print_selection(self, best_ids, maneuvers_by_id):
        for phase in ("pre", "post"):
            selected_row = self._current_print_row(phase)
            if selected_row is not None and self._row_is_maneuver(selected_row):
                maneuver_id = int(self.maneuver_table.item(selected_row, 0).text())
                if self.maneuver_selected.get(maneuver_id, False):
                    continue

            preferred_id = None
            if best_ids[(phase, "fvc")] and best_ids[(phase, "fvc")] == best_ids[(phase, "fev1")]:
                preferred_id = best_ids[(phase, "fvc")]
            if preferred_id is None:
                for row in range(self.maneuver_table.rowCount()):
                    if not self._row_is_maneuver(row) or self._phase_for_row(row) != phase:
                        continue
                    maneuver_id = int(self.maneuver_table.item(row, 0).text())
                    if not self.maneuver_selected.get(maneuver_id, False):
                        continue
                    if not self._quality_errors_from_row(maneuvers_by_id[maneuver_id]):
                        preferred_id = maneuver_id
                        break
            preferred_row = self._row_for_maneuver(preferred_id) if preferred_id is not None else None
            self._set_print_row(preferred_row, phase)

    def _current_print_row(self, phase):
        for row in range(self.maneuver_table.rowCount()):
            if (
                self._row_is_maneuver(row)
                and self._phase_for_row(row) == phase
                and self.maneuver_table.item(row, 3).checkState() == Qt.Checked
            ):
                return row
        return None

    def _phase_for_row(self, row):
        maneuver_id = int(self.maneuver_table.item(row, 0).text())
        return self.maneuver_phase.get(maneuver_id)

    def _row_for_maneuver(self, maneuver_id):
        for row in range(self.maneuver_table.rowCount()):
            if self._row_is_maneuver(row) and int(self.maneuver_table.item(row, 0).text()) == maneuver_id:
                return row
        return None

    def _set_print_row(self, row, phase):
        maneuver_id = None
        self.updating_maneuver_table = True
        for current_row in range(self.maneuver_table.rowCount()):
            if not self._row_is_maneuver(current_row) or self._phase_for_row(current_row) != phase:
                continue
            checked = current_row == row
            self.maneuver_table.item(current_row, 3).setCheckState(Qt.Checked if checked else Qt.Unchecked)
            if checked:
                maneuver_id = int(self.maneuver_table.item(current_row, 0).text())
        self.updating_maneuver_table = False
        db.set_print_selected(self.current_session_id, phase, maneuver_id)

    def refresh_summary_page(self):
        if self.current_session_id is None or not hasattr(self, "summary_table"):
            return
        maneuvers = db.list_maneuvers_for_session(self.current_session_id)
        accepted_pre = [m for m in maneuvers if m["review_status"] == "accepted" and m["phase"] == "pre"]
        accepted_post = [m for m in maneuvers if m["review_status"] == "accepted" and m["phase"] == "post"]
        best_pre = self._summary_best_values(accepted_pre)
        best_post = self._summary_best_values(accepted_post)
        patient = db.get_patient(self.current_patient_id)
        session = db.get_session(self.current_session_id)
        pre_references = gli2012_for_maneuver(patient, session, best_pre) or {}
        post_references = gli2012_for_maneuver(patient, session, best_post) or {}
        rows = [
            ("FVC", "fvc", True),
            ("FEV1", "fev1", True),
            ("FEV1/FVC", "fev1_fvc", False),
            ("FEF 25-75", "fef2575", True),
            ("PEF", "pef", False),
        ]
        from app.respiratory_measurements import summary as respiratory_summary
        extra_records=db.list_respiratory_measurements(self.current_session_id)
        extra=respiratory_summary(extra_records)
        for key,label in (('svc','SVC (L)'),('ic','IC (L)'),('erv','ERV (L)'),('vt','VT SVC (L)'),
                          ('mvv','MVV (L/min)'),('frequency','FR (min⁻¹)')):
            if any(r['kind']==('mvv' if key in ('mvv','frequency') else 'svc') for r in extra_records):
                rows.append((label,key,False))
                best_pre[key]=extra.get(('pre',key));best_post[key]=extra.get(('post',key))
        pre_references.update(respiratory_references(patient,session,best_pre))
        post_references.update(respiratory_references(patient,session,best_post))
        all_predicted={**(self.predicted_values or {}),**respiratory_predicted(patient,session)}
        for i,(label,key,has_percent) in enumerate(rows):
            if key in ('svc','ic','erv','mvv'):rows[i]=(label,key,True)
        self.summary_table.setRowCount(len(rows))
        for row, (label, key, has_predicted_percent) in enumerate(rows):
            predicted = all_predicted.get(key)
            pre_value = best_pre.get(key)
            post_value = best_post.get(key)
            values = [
                label,
                self._fmt_summary_value(key, predicted),
                self._fmt_summary_value(key, pre_value),
                self._summary_value_percent(pre_value, predicted) if has_predicted_percent else "-",
                self._fmt_reference(pre_references,key,"zscore"),
                self._fmt_summary_value(key, post_value),
                self._summary_value_percent(post_value, predicted) if has_predicted_percent else "-",
                self._fmt_reference(post_references,key,"zscore"),
                "-" if pre_value is None or post_value is None else f"{self._percent_change(pre_value, post_value):+.1f}",
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setTextAlignment(Qt.AlignCenter)
                if col == 0:
                    item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                if label in {"FVC", "FEV1", "FEV1/FVC"} and col in {2, 5}:
                    self._set_bold(item)
                self.summary_table.setItem(row, col, item)
            self._color_reference_cells(self.summary_table,row,best_pre,pre_references,{key:(2,3,4)})
            self._color_reference_cells(self.summary_table,row,best_post,post_references,{key:(5,6,7)})

        curves = []
        volume_curves = []
        for phase in ("pre", "post"):
            row = self._current_print_row(phase)
            if row is None:
                continue
            maneuver_id = int(self.maneuver_table.item(row, 0).text())
            curve = self.maneuver_curves.get(maneuver_id)
            if curve:
                curves.append(curve)
            volume_curve=self.maneuver_volume_time_curves.get(maneuver_id)
            if volume_curve:volume_curves.append(volume_curve)
        self.summary_flow_volume_chart.set_curves(curves)
        self.summary_volume_time_chart.set_curves(volume_curves)
        self.summary_zscore_chart.set_rows(self._summary_zscore_rows())
        session = db.get_session(self.current_session_id)
        imported = json.loads(session["source_json"] or "{}").get("origin") == "breeze"
        description = REFERENCE_NOTE if imported else reference_description(session)
        self.summary_reference_note.setText(description)
        self.summary_reference_note.setVisible(bool(description))
        self.measurement_patient_data_label.setToolTip(description)
        self.summary_patient_data_label.setToolTip(description)
        self.summary_zscore_chart.threshold_label = "z = −1.645" if imported else "LLN"
        self.summary_zscore_chart.update()

    def _summary_zscore_rows(self):
        wanted = {"FVC", "FEV1", "FEV1/FVC", "FEF 25-75"}
        rows = []
        for row in range(self.summary_table.rowCount()):
            label_item = self.summary_table.item(row, 0)
            if label_item is None or label_item.text() not in wanted:
                continue
            pre_item = self.summary_table.item(row, 4)
            post_item = self.summary_table.item(row, 7)
            rows.append(
                (
                    label_item.text(),
                    self._parse_optional_float(pre_item.text() if pre_item else None),
                    self._parse_optional_float(post_item.text() if post_item else None),
                )
            )
        return rows

    def _summary_best_values(self, maneuvers):
        from app.history import fvc_summary
        return fvc_summary(maneuvers)

    def _summary_value_zscore(self, key, value):
        if value is None or key == "pef":
            return "-"
        patient = db.get_patient(self.current_patient_id)
        session = db.get_session(self.current_session_id)
        references = gli2012_for_maneuver(patient, session, {key: value})
        return self._fmt_reference(references, key, "zscore")

    @staticmethod
    def _fmt_summary_value(key, value):
        if value is None:
            return "-"
        return f"{value*100:.1f}%" if key == "fev1_fvc" else f"{value:.2f}"

    @staticmethod
    def _summary_value_percent(value, predicted):
        if value is None or not predicted:
            return "-"
        return f"{(value / predicted) * 100:.1f}"

    @staticmethod
    def _fmt_quality(errors):
        labels = {'Tos':'Posible tos', 'Cierre glotico':'Posible cierre glótico'}
        return "OK" if not errors else "; ".join(labels.get(error, error) for error in errors)

    @staticmethod
    def _quality_errors_from_row(maneuver):
        if maneuver["quality_errors_json"]:
            return json.loads(maneuver["quality_errors_json"])
        errors = []
        bev_limit = max(0.100, (maneuver["fvc"] or 0) * 0.05)
        if maneuver["bev"] is not None and maneuver["bev"] > bev_limit:
            errors.append("BEV alto")
        if maneuver["duration"] is not None and maneuver["duration"] < 0.5:
            errors.append("Duracion <0.5 s")
        if not maneuver["eofe_ok"]:
            errors.append("Sin meseta")
        return errors

    def _summary_zscore(self, maneuver, key):
        if not maneuver:
            return "-"
        patient = db.get_patient(self.current_patient_id)
        session = db.get_session(self.current_session_id)
        references = gli2012_for_maneuver(patient, session, {key: maneuver[key]})
        return self._fmt_reference(references, key, "zscore")

    def measurement_failed(self, trace):
        if "Cero inestable o fuera de rango:" in trace:
            self.status_label.setText("Repetir puesta a cero")
            QMessageBox.warning(self, "Puesta a cero incompleta", self._device_error_message(trace))
            return
        self.status_label.setText("Error")
        QMessageBox.critical(self, "Medicion", self._device_error_message(trace))

    @staticmethod
    def _device_error_message(trace, zero_action="Flujo cero"):
        if "Cero inestable o fuera de rango:" in trace:
            return (
                "No se pudo completar la puesta a cero porque la señal no estuvo estable "
                "o quedó fuera del rango esperado.\n\n"
                "Dejá el sensor apoyado e inmóvil, sin soplar ni mover la jeringa.\n\n"
                f"Después presioná «{zero_action}» para repetirla y mantené el sensor "
                "quieto hasta que la aplicación indique que está listo."
            )
        if "USBError" in trace and ("[Errno 13]" in trace or "Access denied" in trace):
            return (
                "El sistema no permitió abrir la conexión USB del espirómetro.\n\n"
                "Puede estar en uso por otra instancia de esta aplicación u otro programa, "
                "o haber un problema con los permisos o el controlador USB.\n\n"
                "Cerrá las otras ventanas del espirómetro, incluida la versión de prueba "
                "iniciada con Python. Desconectá y reconectá el equipo y abrí una sola "
                "instancia de la aplicación. Si usás una máquina virtual, comprobá que "
                "el dispositivo esté conectado al sistema donde ejecutás la app.\n\n"
                "Si continúa, revisá la instalación del controlador USB. "
                "La falta de calibración no causa este error de acceso USB."
            )
        if "Resource busy" in trace or ("USBError" in trace and "[Errno 16]" in trace):
            return (
                "El espirómetro está ocupado y no se puede iniciar la captura.\n\n"
                "Puede estar asignado a una máquina virtual o en uso por otra aplicación.\n\n"
                "Si usás VirtualBox, desmarcá el espirómetro en Dispositivos → USB "
                "para devolverlo a este sistema. Si otra aplicación lo está usando, "
                "detené su captura o cerrala.\n\n"
                "Después volvé a iniciar la maniobra o la calibración."
            )
        if "Dispositivo no encontrado" not in trace:
            return trace
        return (
            "No se pudo iniciar porque la app no detecta el espirometro.\n\n"
            "Como corregirlo:\n"
            "1. Conecte el espirometro al puerto USB.\n"
            "2. Verifique que el cable este bien conectado y que el equipo este encendido.\n"
            "3. Si ya estaba conectado, desconectelo y vuelva a conectarlo.\n"
            "4. Cierre cualquier otro programa que pueda estar usando el dispositivo.\n"
            "5. Vuelva a intentar iniciar la medicion.\n\n"
            "Si el problema continua, pruebe otro puerto USB o reinicie la aplicacion."
        )

    def measurement_thread_finished(self):
        thread = self.thread
        self.device_ready = False
        self.capture_closed()
        self.worker = None
        self.thread = None
        self.update_device_indicator()
        self.zero_button.setEnabled(True)
        self.maneuver_button.setEnabled(False)
        if thread is not None:
            thread.deleteLater()
        if self._device_requested:
            self.ensure_study_device()
        elif self._pending_calibration_start:
            self._pending_calibration_start = False
            if self.stack.currentWidget() == self.calibration_page:
                self.start_calibration_session()

    def closeEvent(self, event):
        self._device_requested = False
        if self.worker is not None:
            self.worker.shutdown()
        if self.calibration_worker is not None:
            self.calibration_worker.shutdown()
        for thread in (self.thread, self.calibration_thread):
            if thread is not None and thread.isRunning():
                thread.quit()
                thread.wait()
        super().closeEvent(event)

    @staticmethod
    def _fmt_metric(value, digits=2):
        return "-" if value is None else f"{value:.{digits}f}"

    @staticmethod
    def _fmt_birth_date(value):
        if not value:
            return "-"
        try:
            return datetime.fromisoformat(value).strftime("%d/%m/%Y")
        except ValueError:
            return value

    @staticmethod
    def _fmt_study_datetime(value):
        if not value:
            return "-"
        try:
            return datetime.fromisoformat(value).strftime("%d/%m/%Y %H:%M")
        except ValueError:
            return value

    @staticmethod
    def _fmt_age(birth_date):
        if not birth_date:
            return "-"
        try:
            born = datetime.fromisoformat(birth_date).date()
        except ValueError:
            return "-"
        today = datetime.now().date()
        years = today.year - born.year - ((today.month, today.day) < (born.month, born.day))
        return f"{years} años"

    @staticmethod
    def _fmt_sex(value):
        return {"F": "Femenino", "M": "Masculino"}.get(value, "-")

    @staticmethod
    def _fmt_reference(references, key, field):
        if not references or not references.get(key):
            return "-"
        value = references[key].get(field)
        if value is None:
            return "-"
        return f"{value:.1f}" if field == "percent" else f"{value:.2f}"
