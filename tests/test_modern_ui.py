"""Exercise presentation against a disposable study, without acquiring USB."""
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from PySide6.QtCore import QPoint, QThread, Qt
from PySide6.QtWidgets import QApplication
from app import db
from app.main_window import MainWindow


class ModernUiTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_patch = patch.object(db, 'DB_PATH', Path(self.tmp.name) / 'test.sqlite3')
        self.db_patch.start()
        self.addCleanup(self.db_patch.stop)
        thread = patch.object(QThread, 'start')
        thread.start()
        self.addCleanup(thread.stop)
        self.window = MainWindow()
        self.addCleanup(self.window.close)
        patient = db.create_patient('Prueba', 'Interfaz', no_btps=True)
        self.study = db.create_session(patient)
        self.keys = []
        for phase in ('pre', 'pre', 'post'):
            key = db.save_maneuver(self.study, {'fvc': 3., 'fev1': 2.5, 'fev1_fvc': 2.5/3,
                'pef': 4., 'duracion': 6., 'vol_curve': [(0., 0., 0.), (1., 3., 4.)]}, [], phase=phase)
            self.keys.append(key)
        self.window.current_patient_id = patient
        self.window.load_study(self.study)

    def test_compact_and_expanded_views_preserve_phase_headers_summaries_and_maneuvers(self):
        w = self.window
        before = [dict(row) for row in db.list_maneuvers_for_session(self.study)]
        visible_ids = lambda: [int(w.maneuver_table.item(r, 0).text())
            for r in range(w.maneuver_table.rowCount()) if w._row_is_maneuver(r) and not w.maneuver_table.isRowHidden(r)]
        labels = [w.maneuver_table.item(r, 1).text() for r in range(w.maneuver_table.rowCount())]
        self.assertEqual(labels[0:2], ['Predicho','PRE'])
        self.assertEqual(labels[4:6], ['ATS','POST'])
        self.assertEqual(labels[-1], 'Compuesto')
        self.assertTrue(w.maneuver_details_button.isChecked())
        self.assertFalse(w.maneuver_table.isColumnHidden(6))
        for expanded in (False, True):
            w.maneuver_details_button.setChecked(expanded)
            self.assertEqual(w.maneuver_table.isColumnHidden(6),not expanded)
            for phase in ('pre','post'):
                w.phase_selector.setCurrentIndex(w.phase_selector.findData(phase))
                self.assertEqual(visible_ids(),self.keys)
                self.assertTrue(all(not w.maneuver_table.isRowHidden(r) for r in range(w.maneuver_table.rowCount())))
        self.assertEqual(before, [dict(row) for row in db.list_maneuvers_for_session(self.study)])
        w.resize(1024, 768)
        w.show()
        self.qt.processEvents()
        self.assertLessEqual(w.minimumSizeHint().width(), 1024)
        self.assertLessEqual(w.minimumSizeHint().height(), 768)

    def test_phase_footer_displays_best_included_values_and_updates_on_exclusion(self):
        w=self.window
        a=db.save_maneuver(self.study,dict(fvc=3.5,fev1=2.6,fev1_fvc=2.6/3.5,pef=5.,fef2575=3.,vol_curve=[]),[])
        b=db.save_maneuver(self.study,dict(fvc=3.2,fev1=2.9,fev1_fvc=2.9/3.2,pef=6.,fef2575=3.5,vol_curve=[]),[])
        w.load_study(self.study)
        pre=w._phase_summary_row('pre');post=w._phase_summary_row('post')
        self.assertEqual(w.maneuver_table.item(pre,4).text(),'3.50')
        self.assertEqual(w.maneuver_table.item(pre,7).text(),'2.90')
        self.assertEqual(w.maneuver_table.item(pre,10).text(),f'{2.9/3.5*100:.1f}%')
        self.assertEqual(w.maneuver_table.item(post,4).text(),'3.00')
        self.assertLess(w._row_for_maneuver(a),pre)
        self.assertLess(pre,w._row_for_maneuver(self.keys[-1]))
        self.assertLess(w._row_for_maneuver(self.keys[-1]),post)
        w.maneuver_table.item(w._row_for_maneuver(b),2).setCheckState(Qt.Unchecked)
        self.assertEqual(w.maneuver_table.item(pre,7).text(),'2.60')
        self.assertEqual(w.maneuver_table.item(post,7).text(),'2.50')

    def test_small_display_keeps_capture_controls_and_scrollable_content_reachable(self):
        from PySide6.QtWidgets import QScrollArea, QTabWidget
        w = self.window
        # Allow for the taskbar and frame on a 1366x768 monitor.
        w.resize(1366, 690)
        w.show()
        self.qt.processEvents()
        for page, controls in (
            (w.measurement_page, (w.maneuver_button, w.zero_button, w.delete_button)),
            (w.svc_page, (w.svc_page.start, w.svc_page.mark, w.svc_page.remove)),
            (w.mvv_page, (w.mvv_page.start, w.mvv_page.mark, w.mvv_page.remove)),
        ):
            w.stack.setCurrentWidget(page)
            self.qt.processEvents()
            self.assertEqual(w.size().toTuple(), (1366, 690))
            for control in controls:
                top_left = control.mapTo(w, QPoint(0, 0))
                self.assertTrue(w.rect().contains(top_left), control.text())
                self.assertTrue(w.rect().contains(top_left + control.rect().bottomRight()), control.text())
                table = w.maneuver_table if page is w.measurement_page else page.table
                self.assertLess(top_left.y() + control.height(), table.mapTo(w, QPoint(0, 0)).y())
            if page is w.measurement_page:
                self.assertGreaterEqual(w.flow_volume_chart.height(), 140)
                self.assertFalse(w.maneuver_table.isColumnHidden(6))
                self.assertLess(w.elapsed_label.mapTo(w, QPoint(0, 0)).y(),
                                w.maneuver_table.mapTo(w, QPoint(0, 0)).y())
        w.show_summary()
        self.qt.processEvents()
        self.assertEqual(w.height(), 690)
        self.assertGreater(w.summary_table.height(), 180)
        scroll = w.summary_scroll
        self.assertGreater(scroll.verticalScrollBar().maximum(), 0)
        scroll.ensureWidgetVisible(w.summary_report_input)
        self.qt.processEvents()
        point = w.summary_report_input.mapTo(scroll.viewport(), QPoint(0, 0))
        self.assertTrue(scroll.viewport().rect().contains(point + w.summary_report_input.rect().center()))
        small_images = w._report_payload()['charts']
        w.resize(1600, 1000)
        self.qt.processEvents()
        large_images = w._report_payload()['charts']
        self.assertEqual([image.size() for image in small_images], [image.size() for image in large_images])
        self.assertTrue(all(a == b for a, b in zip(small_images, large_images)))
        w.resize(1366, 690)
        w.stack.setCurrentWidget(w.settings_page)
        tabs = w.settings_page.findChild(QTabWidget)
        for index in range(tabs.count()):
            tabs.setCurrentIndex(index)
            self.qt.processEvents()
            self.assertIsInstance(tabs.currentWidget(), QScrollArea)
            self.assertEqual(w.height(), 690)

    def test_configured_table_view_defaults_to_full_persists_and_keeps_row_heights(self):
        w=self.window
        self.assertEqual(w.fvc_table_view_combo.currentData(),'full')
        heights=[w.maneuver_table.rowHeight(r) for r in range(w.maneuver_table.rowCount())]
        before=[dict(m) for m in db.list_maneuvers_for_session(self.study)]
        w.fvc_table_view_combo.setCurrentIndex(w.fvc_table_view_combo.findData('compact'))
        self.assertEqual(db.get_setting('fvc_table_view'),'compact')
        self.assertFalse(w.maneuver_details_button.isChecked())
        self.assertTrue(w.maneuver_table.isColumnHidden(6))
        self.assertEqual(heights,[w.maneuver_table.rowHeight(r) for r in range(w.maneuver_table.rowCount())])
        self.assertTrue(all(not w.maneuver_table.isRowHidden(r) for r in range(w.maneuver_table.rowCount())))
        reopened=MainWindow()
        try:
            self.assertEqual(reopened.fvc_table_view_combo.currentData(),'compact')
            self.assertFalse(reopened.maneuver_details_button.isChecked())
        finally:reopened.close()
        w.maneuver_details_button.click()
        self.assertEqual(w.fvc_table_view_combo.currentData(),'full')
        self.assertEqual(db.get_setting('fvc_table_view'),'full')
        self.assertEqual(heights,[w.maneuver_table.rowHeight(r) for r in range(w.maneuver_table.rowCount())])
        self.assertEqual(before,[dict(m) for m in db.list_maneuvers_for_session(self.study)])

    def test_phase_maneuvers_rank_by_fvc_plus_fev1_preserving_time_checks_and_footers(self):
        w=self.window
        examples=[(3.68,2.46),(3.56,2.41),(3.64,2.53),(3.55,2.46)]
        ids=[]
        for fvc,fev1 in examples:
            ids.append(db.save_maneuver(self.study,dict(fvc=fvc,fev1=fev1,fev1_fvc=fev1/fvc,
                pef=5.,vol_curve=[(0.,0.,0.),(1.,fvc,5.)]),[]))
        missing=db.save_maneuver(self.study,dict(fvc=9.,fev1=None,vol_curve=[]),[],review_status='pending')
        w.load_study(self.study)
        ordered=lambda phase:[int(w.maneuver_table.item(row,0).text()) for row in range(w.maneuver_table.rowCount())
                              if w._row_is_maneuver(row) and w._phase_for_row(row)==phase]
        expected=[ids[2],ids[0],ids[3],ids[1],*self.keys[:2],missing]
        self.assertEqual(ordered('pre'),expected)
        self.assertEqual(ordered('post'),self.keys[2:])
        self.assertEqual(w.maneuver_table.item(w._phase_summary_row('pre'),1).text(),'ATS')
        self.assertLess(w._row_for_maneuver(missing),w._phase_summary_row('pre'))
        self.assertEqual(w.maneuver_table.item(w._row_for_maneuver(missing),2).checkState(),Qt.Unchecked)
        # Manual curve printing and the row's identity survive ranking and reopen.
        chosen=ids[0];w.maneuver_table.item(w._row_for_maneuver(chosen),3).setCheckState(Qt.Checked)
        before=[dict(m) for m in db.list_maneuvers_for_session(self.study)]
        w.maneuver_table.selectRow(w._row_for_maneuver(chosen));colors=dict(w.maneuver_colors())
        w.refresh_study_summary()
        self.assertEqual(int(w.maneuver_table.item(w.maneuver_table.currentRow(),0).text()),chosen)
        w.load_study(self.study)
        self.assertEqual(ordered('pre'),expected)
        self.assertEqual(int(w.maneuver_table.item(w._current_print_row('pre'),0).text()),chosen)
        self.assertEqual(w.maneuver_colors(),colors)
        self.assertEqual(before,[dict(m) for m in db.list_maneuvers_for_session(self.study)])

    def test_new_high_scoring_capture_moves_up_without_changing_existing_curve_colors(self):
        w=self.window;colors=dict(w.maneuver_colors())
        previous_print=int(w.maneuver_table.item(w._current_print_row('post'),0).text())
        w.measurement_finished([],dict(fvc=4.,fev1=3.,fev1_fvc=.75,pef=6.,vol_curve=[(0.,0.,0.),(1.,4.,6.)]))
        new=db.list_maneuvers_for_session(self.study)[-1]['id']
        post_rows=[row for row in range(w.maneuver_table.rowCount()) if w._row_is_maneuver(row) and w._phase_for_row(row)=='post']
        self.assertEqual(int(w.maneuver_table.item(post_rows[0],0).text()),new)
        self.assertEqual(int(w.maneuver_table.item(w.maneuver_table.currentRow(),0).text()),new)
        self.assertEqual({key:w.maneuver_colors()[key] for key in colors},colors)
        self.assertEqual(int(w.maneuver_table.item(w._current_print_row('post'),0).text()),previous_print)
        self.assertEqual(w.maneuver_table.item(w._phase_summary_row('post'),4).text(),'4.00')

    def test_selected_curve_and_colors_survive_excluding_another_and_reloading(self):
        w = self.window
        colors = list(w.flow_volume_chart.curve_colors)
        second = w._row_for_maneuver(self.keys[1])
        w.maneuver_table.selectRow(second)
        self.assertEqual(w.flow_volume_chart.highlighted_curve, 1)
        first = w._row_for_maneuver(self.keys[0])
        w.maneuver_table.item(first, 2).setCheckState(Qt.Unchecked)
        self.assertEqual(w.flow_volume_chart.curve_colors, colors[1:])
        self.assertEqual(w.flow_volume_chart.highlighted_curve, 0)
        # Clearing a selected table must not address stale curve IDs.
        w.load_study(self.study)
        self.assertEqual(len(w.flow_volume_chart.curves), 2)
        self.assertEqual(w.flow_volume_chart.curve_colors, colors[1:])

    def test_completed_capture_appears_immediately_with_existing_curves(self):
        w = self.window
        curve = [(0., 0., 0.), (1., 3., 4.)]
        w.measurement_finished([], {'fvc': 3., 'fev1': 2.5, 'pef': 4.,
            'duracion': 6., 'vol_curve': curve})
        self.assertEqual(len(w.flow_volume_chart.curves), 4)
        self.assertEqual(w.flow_volume_chart.curves[-1], curve)
        self.assertEqual(len(w.flow_volume_chart.curve_colors), 4)
        self.assertEqual(len(db.list_maneuvers_for_session(self.study)), 4)

    def test_action_icons_keep_contrast_in_dark_system_theme(self):
        from PySide6.QtCore import QSize
        from PySide6.QtGui import QColor, QIcon, QPalette
        from app.ui_icons import set_button_icon
        from PySide6.QtWidgets import QStyle
        old_palette = self.qt.palette()
        dark_palette = QPalette(old_palette)
        dark_palette.setColor(QPalette.ButtonText, QColor('#ffffff'))
        dark_palette.setColor(QPalette.Window, QColor('#202020'))
        self.qt.setPalette(dark_palette)
        try:
            w = self.window
            for button, enabled_color, disabled_color in (
                    (w.zero_button, '#20303d', '#85949d'),
                    (w.delete_button, '#087f83', '#85949d'),
                    (w.maneuver_button, '#ffffff', '#566d76'),
                    (w.patients_button, '#ffffff', '#8195a0')):
                for mode, expected in ((QIcon.Normal, enabled_color), (QIcon.Disabled, disabled_color)):
                    image = button.icon().pixmap(QSize(32, 32), mode).toImage()
                    self.assertEqual(image.pixelColor(0, 0).alpha(), 0)
                    colors = {image.pixelColor(x, y).name() for x in range(image.width())
                              for y in range(image.height()) if image.pixelColor(x, y).alpha() > 240}
                    self.assertIn(expected, colors)
            # The stop/start change must keep the primary button's light icon.
            set_button_icon(w.maneuver_button, QStyle.SP_MediaStop)
            image = w.maneuver_button.icon().pixmap(QSize(32, 32)).toImage()
            self.assertEqual(image.pixelColor(16, 16).name(), '#ffffff')
        finally:
            self.qt.setPalette(old_palette)

    def test_study_tabs_stay_visible_and_selected_on_both_pages(self):
        w = self.window
        w.show()
        self.qt.processEvents()
        tabs = w.study_tabs
        before = [dict(row) for row in db.list_maneuvers_for_session(self.study)]
        for width, height in ((1280, 840), (1920, 1000), (1024, 768)):
            w.resize(width, height)
            self.qt.processEvents()
            self.assertIs(tabs.parentWidget(), w.measurement_page)
            self.assertTrue(tabs.isVisible())
            self.assertTrue(w.measurement_tab.isChecked())
            self.assertFalse(w.measurement_summary_tab.isChecked())
            name_position = w.measurement_patient_label.mapTo(w, QPoint(0, 0))
            details_position = w.measurement_patient_data_label.mapTo(w, QPoint(0, 0))
            tabs_position = tabs.mapTo(w, QPoint(0, 0))
            w.measurement_summary_tab.click()
            self.qt.processEvents()
            self.assertEqual(w.summary_patient_label.mapTo(w, QPoint(0, 0)), name_position)
            self.assertEqual(w.summary_patient_data_label.mapTo(w, QPoint(0, 0)), details_position)
            self.assertEqual(tabs.mapTo(w, QPoint(0, 0)), tabs_position)
            self.assertIs(w.stack.currentWidget(), w.summary_page)
            self.assertIs(w.study_tabs, tabs)
            self.assertIs(tabs.parentWidget(), w.summary_page)
            self.assertTrue(tabs.isVisible())
            self.assertTrue(w.measurement_summary_tab.isChecked())
            self.assertFalse(w.measurement_tab.isChecked())
            self.assertFalse(w.maneuver_space_shortcut.isEnabled())
            w.measurement_tab.click()
            self.qt.processEvents()
            self.assertIs(w.stack.currentWidget(), w.measurement_page)
            self.assertTrue(w.maneuver_space_shortcut.isEnabled())
        self.assertEqual(before, [dict(row) for row in db.list_maneuvers_for_session(self.study)])

    def test_scrollable_pages_keep_light_gaps_with_dark_system_palette(self):
        from PySide6.QtGui import QColor, QPalette
        from PySide6.QtWidgets import QScrollArea
        original = self.qt.palette()
        dark = QPalette(original)
        for color_role in (QPalette.Window, QPalette.Base, QPalette.Button):
            dark.setColor(color_role, QColor('#202020'))
        self.qt.setPalette(dark)
        window = None
        try:
            window = MainWindow()
            window.current_patient_id = self.window.current_patient_id
            window.load_study(self.study)
            window.resize(1366, 690)
            window.show()
            window.show_summary()
            self.qt.processEvents()
            body = window.summary_scroll.widget()
            top = window.summary_table.geometry().bottom()+1
            bottom = window.summary_zscore_chart.geometry().top()
            self.assertGreater(bottom, top)
            self.assertEqual(body.grab().toImage().pixelColor(10, (top+bottom)//2).name(), '#f3f6f8')
            for scroll in window.findChildren(QScrollArea):
                if scroll.property('scrollBackground'):
                    for surface in (scroll, scroll.viewport(), scroll.widget()):
                        self.assertTrue(surface.property('scrollBackground'))
                        self.assertEqual(surface.palette().color(QPalette.Window).name(), '#f3f6f8')
        finally:
            if window is not None:
                window.close()
            self.qt.setPalette(original)

    def test_combo_popup_frame_and_padding_stay_light_in_dark_theme(self):
        from PySide6.QtGui import QColor, QPalette
        original = self.qt.palette()
        dark = QPalette(original)
        dark.setColor(QPalette.Window, QColor('#202020'))
        dark.setColor(QPalette.Base, QColor('#202020'))
        self.qt.setPalette(dark)
        try:
            w = self.window
            w.show()
            for page, combo in ((w.mvv_page, w.mvv_page.option),
                                (w.svc_page, w.svc_page.option),
                                (w.mvv_page, w.mvv_page.phase)):
                w.stack.setCurrentWidget(page)
                self.qt.processEvents()
                popup = combo.view().window()
                popup.setPalette(dark)
                popup.setContentsMargins(0, 8, 0, 8)
                combo.showPopup()
                try:
                    self.qt.processEvents()
                    # Native desktop styles may leave menu padding above/below
                    # the list; it must use the same light background.
                    popup.resize(popup.width(), popup.height()+16)
                    self.qt.processEvents()
                    image = popup.grab().toImage()
                    for y in (2, image.height()-3):
                        self.assertEqual(image.pixelColor(image.width()//2, y).name(), '#ffffff')
                    self.assertEqual(combo.view().palette().color(QPalette.Base).name(), '#ffffff')
                finally:
                    combo.hidePopup()
        finally:
            self.qt.setPalette(original)

    def test_patient_row_number_strip_stays_light_below_last_row(self):
        from PySide6.QtGui import QColor, QPalette
        from PySide6.QtWidgets import QAbstractButton
        original = self.qt.palette()
        dark = QPalette(original)
        dark.setColor(QPalette.Window, QColor('#202020'))
        dark.setColor(QPalette.Base, QColor('#202020'))
        self.qt.setPalette(dark)
        w = None
        try:
            w = MainWindow()
            w.show_patients()
            w.resize(1366, 690)
            w.show()
            self.qt.processEvents()
            header = w.patient_table.verticalHeader()
            image = header.viewport().grab().toImage()
            self.assertEqual(image.pixelColor(image.width()//2, image.height()-4).name(), '#f7fafb')
            corner = w.patient_table.findChild(QAbstractButton)
            self.assertIsNotNone(corner)
            image = corner.grab().toImage()
            self.assertEqual(image.pixelColor(image.width()//2, image.height()//2).name(), '#f7fafb')
        finally:
            if w is not None:
                w.close()
            self.qt.setPalette(original)

    def test_file_chooser_sidebar_stays_light_with_dark_system_palette(self):
        from PySide6.QtGui import QColor, QPalette
        from PySide6.QtWidgets import QFileDialog, QListView
        from app.ui_theme import file_dialog
        original = self.qt.palette()
        dark = QPalette(original)
        for role in (QPalette.Window, QPalette.Base, QPalette.Button):
            dark.setColor(role, QColor('#202020'))
        for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
            dark.setColor(role, QColor('#eeeeee'))
        self.qt.setPalette(dark)
        try:
            for save in (True, False):
                dialog = file_dialog(self.window, 'Archivo', 'PDF (*.pdf)', 'informe.pdf', save)
                try:
                    dialog.setDirectory(self.tmp.name)
                    dialog.show()
                    self.qt.processEvents()
                    self.assertTrue(dialog.testOption(QFileDialog.DontUseNativeDialog))
                    sidebar = dialog.findChild(QListView, 'sidebar')
                    image = sidebar.viewport().grab().toImage()
                    self.assertEqual(image.pixelColor(image.width()-5, image.height()-5).name(), '#ffffff')
                    self.assertEqual(sidebar.palette().color(QPalette.Text).name(), '#20303d')
                    self.assertEqual(dialog.acceptMode(), QFileDialog.AcceptSave if save else QFileDialog.AcceptOpen)
                    from PySide6.QtCore import QFileInfo, QSize
                    from PySide6.QtWidgets import QToolButton
                    icons = [dialog.findChild(QToolButton, name).icon() for name in (
                        'backButton', 'forwardButton', 'toParentButton', 'newFolderButton',
                        'listModeButton', 'detailModeButton')]
                    icons += [dialog.iconProvider().icon(QFileInfo(self.tmp.name)),
                              dialog.iconProvider().icon(QFileInfo(str(db.DB_PATH)))]
                    for icon in icons:
                        pixels = icon.pixmap(QSize(24, 24)).toImage()
                        colors = {pixels.pixelColor(x, y).name() for x in range(pixels.width())
                                  for y in range(pixels.height()) if pixels.pixelColor(x, y).alpha() > 128}
                        self.assertTrue(any(all(abs(a-b) <= 2 for a, b in zip(
                            QColor(color).getRgb()[:3], (32, 48, 61))) for color in colors), colors)

                finally:
                    dialog.close()
                    dialog.deleteLater()
        finally:
            self.qt.setPalette(original)

    def test_nested_dialogs_and_print_preview_get_light_theme_automatically(self):
        from PySide6.QtGui import QColor, QIcon, QPalette, QPixmap
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QPushButton, QToolButton
        from PySide6.QtPrintSupport import QPrintPreviewDialog, QPrinter
        from PySide6.QtCore import QSize
        original = self.qt.palette()
        dark = QPalette(original)
        dark.setColor(QPalette.Window, QColor('#202020'))
        dark.setColor(QPalette.WindowText, QColor('#eeeeee'))
        self.qt.setPalette(dark)
        dialogs = []
        try:
            parent = QDialog(self.window)
            nested = QDialog(parent)
            dialogs += [parent, nested]
            layout = QVBoxLayout(nested)
            button = QPushButton('Aceptar')
            white_icon = QPixmap(16, 16)
            white_icon.fill(Qt.white)
            button.setIcon(QIcon(white_icon))
            layout.addWidget(button)
            printer = QPrinter()
            preview = QPrintPreviewDialog(printer, self.window)
            preview._printer = printer
            dialogs.append(preview)
            for dialog in dialogs:
                dialog.show()
                self.qt.processEvents()
                self.assertEqual(dialog.palette().color(QPalette.Window).name(), '#f3f6f8')
                self.assertEqual(dialog.palette().color(QPalette.WindowText).name(), '#20303d')
                self.assertTrue(hasattr(dialog, '_light_style'))
            image = button.icon().pixmap(QSize(16, 16)).toImage()
            self.assertEqual(image.pixelColor(8, 8).name(), '#20303d')
            for tool in preview.findChildren(QToolButton):
                action = tool.defaultAction()
                if action is not None and not action.icon().isNull():
                    self.assertTrue(action.property('iconKind') or
                                    action.property('contrastIconKey') == action.icon().cacheKey())
        finally:
            for dialog in reversed(dialogs):
                dialog.close()
                dialog.deleteLater()
            from PySide6.QtCore import QCoreApplication, QEvent
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            self.qt.setPalette(original)
