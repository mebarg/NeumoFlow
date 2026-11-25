"""Frozen distribution check; never opens USB or the patient database."""
import json
import ctypes
from pathlib import Path
import traceback


def run(report_path):
    result={'ok':False}
    try:
        from PySide6.QtWidgets import QApplication, QWidget
        from PySide6.QtGui import QRawFont
        from app.cpfs_signal import default_table, TABLE_SHA256
        from app.reference_values import gli2012_for_maneuver
        from app.spirometry import find_libusb_package_library
        q=QApplication.instance() or QApplication([])
        font=QRawFont.fromFont(q.font())
        assert font.isValid(), (
            'Qt no pudo cargar fuentes del sistema. En Windows usar '
            'QT_QPA_PLATFORM=windows; el modo offscreen puede carecer de fuentes.'
        )
        widget=QWidget()
        widget.resize(64,64)
        assert not widget.grab().isNull(), 'Qt no pudo dibujar'
        widget.close()
        from app.branding import app_icon
        assert not app_icon().pixmap(32,32).isNull(), 'Falta el icono NeumoFlow incluido'
        table=default_table()
        assert len(table.inputs)==1025, 'Tabla CPFS incompleta'
        patient={'sex':'F','ethnicity':'caucasian','birth_date':'1970-01-01'}
        session={'height_cm':165.,'created_at':'2026-10-26T12:00:00'}
        refs=gli2012_for_maneuver(patient,session,{'fvc':3.,'fev1':2.,'fev1_fvc':2/3})
        assert refs and refs['fvc']['predicted']>0, 'Faltan referencias GLI'
        from app.gli_global import reference
        global_ref=reference('F', 45., 170., 'fvc', 3.)
        assert abs(global_ref['predicted']-3.75921319837854)<1e-10, 'Faltan o cambiaron los datos GLI Global'
        from app.gli_volumes import reference as volume_reference
        volume_ref=volume_reference('M',40.,175.,'svc',5.,'caucasian')
        assert abs(volume_ref['predicted']-5.37)<.01, 'Faltan o cambiaron los datos GLI 2021 volúmenes'
        library=find_libusb_package_library()
        assert library, 'Falta la biblioteca libusb incluida'
        loaded=ctypes.CDLL(library)
        assert loaded.libusb_init and loaded.libusb_get_device_list, 'Biblioteca USB incorrecta'
        result.update(ok=True,qt=True,qt_fonts=True,qt_platform=q.platformName(),
                      font_family=font.familyName(),gli=True,gli_global=True,
                      gli_volumes=True,libusb_library_loaded=True,table_sha256=TABLE_SHA256)
    except Exception:
        result['error']=traceback.format_exc()
    Path(report_path).write_text(json.dumps(result,indent=2),encoding='utf-8')
    return 0 if result['ok'] else 1
