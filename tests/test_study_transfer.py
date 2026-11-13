"""Synthetic transactional interchange tests; never use the user's database."""
import copy
from contextlib import closing
import hashlib
import json
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import sqlite3
import struct
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from zipfile import ZipFile, ZIP_DEFLATED

from app import db
from app.breeze_crypto import _decrypt_block, _expand
from app.study_transfer import (Study, TransferError, import_studies, export_studies,
                                read_package, scan_folder, read_breeze, validate)


def fixture(uid='visit-one', dni='SYNTHETIC'):
    date = '2024-06-17T10:23:45'
    patient = dict(transfer_uid='patient:'+dni, last_name='Muñoz', first_name='Prueba', dni=dni,
        birth_date='1980-02-15', sex='F', ethnicity='caucasian', height_cm=165., weight_kg=60.,
        created_at=date, no_btps=0)
    session = dict(transfer_uid=uid, created_at=date, calibration_date='2024-06-17',
        height_cm=165., weight_kg=60., notes='Informe original: ñ y acentos.', source_json=None)
    m = dict(created_at=date, accepted=1, review_status='accepted', phase='pre', print_selected=1,
        fvc=3.123456789, fev1=2.412345678, fev1_fvc=.7723, pef=4.1234, fef2575=2.2345,
        duration=6., bev=.021, eofe_ok=1, quality_errors_json='[]', samples_json='[[0,1,2,3]]',
        processing_json=json.dumps({'acq_curve': [[0., 0., 0.], [1., 3.1, 4.]], 'extra': {'preserve': 123.456}}))
    return Study(patient, session, [m])


def cow_bytes():
    def text(s):return s.encode('cp1252')+b'\0'
    def fld(k,v):return text(k)+v
    def rec(k,*fields):return text(k)+b''.join(fields)+b'%LastField%\0'
    dt=struct.pack('<8H',2024,6,17,10,23,45,0,0)
    # Explicit valid version-10 time/volume/flow source block.
    channels=b''.join(struct.pack('<BBhBB2h', k, 199, scale, 0, 188, *vals)
        for k,scale,vals in ((2,1000,(0,3123)),(1,200,(0,200)),(3,1000,(0,4123))))
    blob=struct.pack('<IIhhh2sI4s',10,24+len(channels),3,2,0,b'xx',0,b'abcd')+channels
    return ((b'  510\0'+text('6.4.1')).ljust(144,b'\0')+
        rec('Patient',fld('PatientIDNum',text('SYNTHETIC')),fld('PatientLastName',text('Muñoz')),
            fld('SexListID',b'\x02'),fld('SyringeFlag',struct.pack('<I',1)))+
        rec('PatVisit',fld('PatientIDNum',text('SYNTHETIC')),fld('VisitDateTime',dt),
            fld('PFConsult',text('Informe fuente')))+
        rec('FVLData',fld('PatientIDNum',text('SYNTHETIC')),fld('VisitDateTime',dt),fld('EffortTime',dt),
            fld('EffortTypeID',b'\x00'),fld('EffortSelected',struct.pack('<I',0)),fld('PFProtocolStageIndex',b'\x03'),
            fld('FVC',struct.pack('<d',3.123456789)),fld('FEV1FVC',struct.pack('<d',79.35)),
            fld('FEFMax',struct.pack('<d',4.123)),fld('FVLExpiratorySourceData',struct.pack('<I',len(blob))+blob)))


class StudyTransferTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.patch = patch.object(db,'DB_PATH',self.root/'test.sqlite3')
        self.patch.start();self.addCleanup(self.patch.stop)
        db.init_db()

    def counts(self):
        with db.connect() as c:
            return tuple(c.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in ('patients','sessions','maneuvers'))

    def test_rc2_published_vectors_including_128_bit_profile(self):
        for key,bits,cipher,plain in (
            ('0000000000000000',63,'ebb773f993278eff','0000000000000000'),
            ('ffffffffffffffff',64,'278b27e42e2f0d49','ffffffffffffffff'),
            ('3000000000000000',64,'30649edf9be7d2c2','1000000000000001'),
            ('88bca90e90875a7f0f79c384627bafb2',128,'2269552ab0f85ca6','0000000000000000')):
            self.assertEqual(_decrypt_block(bytes.fromhex(cipher),_expand(bytes.fromhex(key),bits)),bytes.fromhex(plain))

    def test_encrypted_profile_matches_plain_export_without_external_provider(self):
        import base64
        from app.breeze_cow import CowFormatError
        header = bytearray(256)
        header[:12] = b'~Encrypted~\0'
        header[12:18] = b'510\0xx'  # reserved bytes need not be zero
        header[18:24] = b'6.4.1\0'
        header[24:34] = b'SYNTHETIC\0'
        # Independent OpenSSL RC2-128-CBC result for cow_bytes(), generated once.
        ciphertext = base64.b64decode('PLlTcFKiwFTp2SsVbQciL9W2FnpgaUQk3xah23ucfquLgYik5/oBP46/9eW4iulLyIfZo4+EvboVfM7CQ8XMU/hVA3Fdl/QoTuPaUSWhso2j04oAyGTcz57yzibK6/X/QJiGTP7slg36Amvm0ByeayfMBpKOZaQzspWq6CPhkm5cRdOI896EUPlAxNMsQRq326aqNt7Z9lEBPF0QhcTrK6EDNHOXPeUHlCDMmVxQNOp0us6z0xVAsyCNwQBAXTMGSwGI7ywot18Aj+fDn+gFPx5++1boi4XRUp3vMmwVyr8qQVFqkrNFH4CW11GfOWVxtexYAsTS0CJWxH1ffuLAn3vK2s52vXEytuWd/c/ucA23SK1o+C+MyW3tUh5HXcXIw+hzHsCgqYcbqfO2jL6e9IqtSv4c9w3DAhK3/yLgfoqJoI9CcpCjB/qrBD3ymcVq0FMHHaVGtucnL9wbFVOy+oR7bwiIuo4spSiigB+4glbAWLqpqg4f7fdtoGOMw40NXsPwdMM6VdwjPIsB/PLAfJFOcyQHpgsiy+OuxUmbiLWXwSUf5HqU5JEQ/Q5egkQDeGcnVVq7i8Nd04AyOVPV3itYO/AVm3ov/PBaB4ftkm1dc3DD9lIovFM/dzK+SYqK9J9E58g7gYM=')
        plain = self.root/'plain.cow';encrypted=self.root/'encrypted.cow'
        plain.write_bytes(cow_bytes());encrypted.write_bytes(bytes(header)+ciphertext)
        a,b=read_breeze(plain),read_breeze(encrypted)
        self.assertEqual(a.patient,b.patient)
        self.assertEqual(a.maneuvers,b.maneuvers)
        self.assertEqual(a.uid,b.uid)
        encrypted.write_bytes(bytes(header)+ciphertext[:-1]+bytes([ciphertext[-1]^1]))
        with self.assertRaises(CowFormatError):read_breeze(encrypted)

    def test_native_roundtrip_preserves_every_field_and_duplicate_identity(self):
        one=fixture();two=fixture('visit-two');two.session['created_at']='2024-07-17T12:23:45';two.maneuvers[0]['phase']='post'
        import_studies([one,two]);ids=[r['id'] for r in db.list_sessions_for_patient(db.list_patients()[0]['id'])]
        target=self.root/'bundle.espiro';self.assertEqual(export_studies(target,ids),2)
        decoded=read_package(target);self.assertEqual(len(decoded),2)
        by_uid={s.uid:s for s in decoded}
        self.assertEqual(by_uid[one.uid].patient,one.patient)
        self.assertEqual(by_uid[one.uid].session,one.session)
        self.assertEqual(by_uid[one.uid].maneuvers,one.maneuvers)
        result=import_studies(decoded);self.assertEqual(result['skipped'],2);self.assertEqual(self.counts(),(1,2,2))
        with patch.object(db,'DB_PATH',self.root/'new-install.sqlite3'):
            db.init_db();import_studies(decoded);self.assertEqual(self.counts(),(1,2,2))
            sid=db.list_sessions_for_patient(db.list_patients()[0]['id'])[-1]['id']
            self.assertEqual(db.list_maneuvers_for_session(sid)[0]['fvc'],one.maneuvers[0]['fvc'])

    def test_duplicates_omit_then_explicit_replace_with_valid_backup(self):
        original=fixture();import_studies([original]);changed=copy.deepcopy(original)
        changed.session['notes']='Informe cambiado';changed.maneuvers[0]['fvc']=9.;changed.patient['last_name']='No sobrescribir ficha'
        self.assertEqual(import_studies([changed])['skipped'],1)
        sid=db.list_sessions_for_patient(db.list_patients()[0]['id'])[0]['id']
        self.assertEqual(db.get_session(sid)['notes'],original.session['notes'])
        result=import_studies([changed],replace=True);self.assertEqual(result['replaced'],1)
        with closing(sqlite3.connect(result['backup'])) as c:
            self.assertEqual(c.execute('SELECT notes FROM sessions').fetchone()[0],original.session['notes'])
            self.assertEqual(c.execute('SELECT fvc FROM maneuvers').fetchone()[0],original.maneuvers[0]['fvc'])
        self.assertEqual(db.list_patients()[0]['last_name'],'Muñoz');self.assertEqual(self.counts(),(1,1,1))
        sid=db.list_sessions_for_patient(db.list_patients()[0]['id'])[0]['id']
        self.assertEqual(db.get_session(sid)['notes'],'Informe cambiado')

    def test_cross_patient_uid_conflict_cannot_replace_another_patient(self):
        import_studies([fixture()]);other=fixture(dni='OTHER')
        with self.assertRaisesRegex(TransferError,'otro paciente'):
            import_studies([other],replace=True)
        self.assertEqual(self.counts(),(1,1,1))

    def test_transaction_rolls_back_prior_inserts_on_database_failure(self):
        with db.connect() as c:
            c.execute("CREATE TRIGGER fail_test BEFORE INSERT ON maneuvers WHEN NEW.fvc=9 BEGIN SELECT RAISE(ABORT,'test failure'); END")
        one=fixture();two=fixture('two','OTHER');two.maneuvers[0]['fvc']=9.
        with self.assertRaises(sqlite3.IntegrityError):import_studies([one,two])
        self.assertEqual(self.counts(),(0,0,0))

    def test_breeze_maps_units_preserves_source_and_unselected_maneuver(self):
        p=self.root/'source.cow';raw=cow_bytes();p.write_bytes(raw)
        s=read_breeze(p);self.assertEqual(s.maneuvers[0]['fev1_fvc'],.7935)
        self.assertEqual(s.maneuvers[0]['pef'],4.123);self.assertEqual(s.maneuvers[0]['phase'],'post')
        self.assertEqual(s.maneuvers[0]['review_status'],'excluded');self.assertEqual(s.patient['no_btps'],1)
        self.assertEqual(s.maneuvers[0]['fvc'],3.123456789)
        self.assertEqual(json.loads(s.maneuvers[0]['processing_json'])['acq_curve'][-1],[1.,3.123,4.123])
        self.assertEqual(p.read_bytes(),raw)
        import_studies([s]);target=self.root/'roundtrip.espiro';export_studies(target,[db.list_sessions_for_patient(db.list_patients()[0]['id'])[0]['id']])
        self.assertEqual(read_package(target)[0].maneuvers,s.maneuvers)
        found,errors=scan_folder(self.root);self.assertEqual(len(found),1);self.assertTrue(found[0].duplicate_id)
        self.assertTrue(errors)  # COW and our package refer to the same historical visit.

    def test_invalid_version_hash_and_curve_are_rejected_without_writes(self):
        import_studies([fixture()]);target=self.root/'good.espiro'
        export_studies(target,[db.list_sessions_for_patient(db.list_patients()[0]['id'])[0]['id']])
        with ZipFile(target) as z:members={n:z.read(n) for n in z.namelist()}
        for kind in ('version','hash','curve'):
            entries=dict(members);manifest=json.loads(entries['manifest.json']);name=manifest['studies'][0]['file']
            if kind=='version':manifest['version']=99
            elif kind=='hash':entries[name]+=b' '
            else:
                s=json.loads(entries[name]);m=s['maneuvers'][0];m['processing_json']='{"acq_curve":[[1,2,"bad"]]}'
                entries[name]=json.dumps(s).encode();manifest['studies'][0]['sha256']=hashlib.sha256(entries[name]).hexdigest()
            entries['manifest.json']=json.dumps(manifest).encode();bad=self.root/(kind+'.espiro')
            with ZipFile(bad,'w',ZIP_DEFLATED) as z:
                for name,data in entries.items():z.writestr(name,data)
            with self.assertRaises(TransferError):read_package(bad)
        self.assertEqual(self.counts(),(1,1,1))

    def test_repeat_migration_keeps_existing_uids_and_native_export(self):
        pid=db.create_patient('Nativo','Paciente',dni='NATIVE')
        sid=db.create_session(pid,calibration_date='2024-01-01')
        db.save_maneuver(sid,{'fvc':3.,'vol_curve':[[0.,0.,0.],[1.,3.,3.]]},[])
        before=db.get_session(sid)['transfer_uid'];db.init_db();self.assertEqual(db.get_session(sid)['transfer_uid'],before)
        self.assertTrue(export_studies(self.root/'native.espiro',[sid]))

class TransferUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.qt=QApplication.instance() or QApplication([])

    def test_preview_duplicates_need_option_and_explicit_row_selection(self):
        from PySide6.QtCore import Qt
        from app.transfer_dialog import TransferDialog
        tmp=TemporaryDirectory();self.addCleanup(tmp.cleanup)
        with patch.object(db,'DB_PATH',Path(tmp.name)/'test.sqlite3'):
            db.init_db();item=fixture();import_studies([item]);item.duplicate_id=1
            dialog=TransferDialog();self.addCleanup(dialog.close)
            dialog.scanned(([item], [('broken.cow','Archivo dañado')]))
            self.assertFalse(dialog.replace_box.isChecked())
            self.assertEqual(dialog.table.item(0,0).checkState(),Qt.Unchecked)
            dialog.replace_box.setChecked(True)
            self.assertEqual(dialog.table.item(0,0).checkState(),Qt.Unchecked)
            dialog.select_rows(True)
            self.assertEqual(dialog.table.item(0,0).checkState(),Qt.Checked)
            dialog.table.selectRow(0)
            self.assertIn('Archivo dañado',dialog.details.toPlainText())

    def test_imported_references_and_quality_are_not_reclassified_as_gli(self):
        from app.reference_values import gli2012_for_maneuver,gli2012_predicted
        from app.main_window import MainWindow
        s=fixture();s.session['source_json']=json.dumps({'origin':'breeze','predicted':{'fvc':4.2,'fev1_fvc':.8}})
        refs=gli2012_for_maneuver(s.patient,s.session,{'fvc':3.})
        self.assertEqual(refs['fvc']['predicted'],4.2)
        self.assertIsNone(refs['fvc']['lln'])
        self.assertEqual(MainWindow._fmt_reference(refs,'fvc','zscore'),'-')
        self.assertEqual(gli2012_predicted(s.patient,s.session)['fvc'],4.2)


if __name__=='__main__':unittest.main()
