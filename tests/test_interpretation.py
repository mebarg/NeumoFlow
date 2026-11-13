from copy import deepcopy
import json
import unittest

from app.interpretation import generate_report
from app.cpfs_environment import measurement_environment

PATIENT={'no_btps':False,'birth_date':'1970-01-01','sex':'F','ethnicity':'caucasian'}
SESSION={'created_at':'2026-10-24T10:00:00','height_cm':165.}


def refs(patient,session,values):
    return {'fvc':{'lln':3.,'predicted':5.},'fev1':{'lln':2.,'predicted':4.},
            'fev1_fvc':{'lln':.7,'predicted':.8}}


def records(fvc=4.,fev1=3.,phase='pre'):
    env=measurement_environment('patient',22.,764.,86.,30.)
    processing={'inicio_aceptable':True,'fev1_tiempo_cubierto':True,'meseta_eofe':True,'environment':env}
    return [{'review_status':'accepted','phase':phase,'fvc':fvc,'fev1':fev1,
             'quality_errors_json':'[]','processing_json':json.dumps(processing)} for i in range(3)]


class InterpretationTests(unittest.TestCase):
    def report(self,rows,**kwargs):
        return generate_report(PATIENT,SESSION,rows,references=refs,**kwargs)

    def test_patterns_and_exact_lower_limit(self):
        for fvc,fev1,expected in [(4,3,'dentro de los límites'),(4,2.8,'dentro de los límites'),
                                  (4,2,'alteración ventilatoria obstructiva'),
                                  (2.5,2.3,'FVC reducida con cociente'),
                                  (2.5,1,'no se confirma un patrón mixto')]:
            with self.subTest(fvc=fvc,fev1=fev1):
                self.assertIn(expected,self.report(records(fvc,fev1)))
        self.assertIn('confirmar restricción',self.report(records(2.5,2.3)))

    def test_missing_quality_reference_and_environment_suppress_pattern(self):
        for kind in ('quality','environment','legacy','short','nonfinite'):
            rows=records(4,2)
            if kind=='quality':rows[0]['quality_errors_json']='["BEV alto"]'
            elif kind=='environment':
                p=json.loads(rows[0]['processing_json']);p['environment']={};rows[0]['processing_json']=json.dumps(p)
            elif kind=='legacy':rows[0]['processing_json']=None
            elif kind=='short':rows=rows[:1]
            else:rows[0]['fvc']=float('nan')
            text=self.report(rows)
            self.assertIn('Interpretación del patrón no emitida',text)
            self.assertNotIn('Hallazgos compatibles',text)
        text=generate_report(PATIENT,SESSION,records(),references=lambda *a:None)
        self.assertIn('referencias GLI incompletas',text)

    def test_repeatability_and_child_age_rule(self):
        rows=records()
        rows[1]['fvc']=3.6
        rows[2]['fvc']=3.55
        self.assertIn('FVC no repetible',self.report(rows))
        small=records(1.,.8)
        small[1]['fvc']=small[2]['fvc']=.88
        adult=self.report(small)
        child=generate_report({**PATIENT,'birth_date':'2021-01-01'},SESSION,small,references=refs)
        self.assertNotIn('FVC no repetible',adult)
        self.assertIn('FVC no repetible',child)

    def test_response_is_strictly_greater_than_ten_percent_predicted(self):
        text=self.report(records()+records(4.,3.4,'post'))
        self.assertIn('No alcanza el criterio',text)
        text=self.report(records()+records(4.,3.4001,'post'))
        self.assertIn('Respuesta significativa según',text)
        self.assertIn('no establece por sí sola asma ni EPOC',text)

    def test_response_with_quality_or_environment_mismatch_is_not_classified(self):
        post=records(4.,3.6,'post')
        post[0]['quality_errors_json']='["Tos"]'
        self.assertIn('Respuesta broncodilatadora no evaluada',self.report(records()+post))
        post=records(4.,3.6,'post')
        for row in post:
            p=json.loads(row['processing_json']);p['environment']['conditions']['temperature_C']=24.
            row['processing_json']=json.dumps(p)
        self.assertIn('condiciones de adquisición PRE/POST no coinciden',self.report(records()+post))

    def test_syringe_empty_and_excluded_maneuvers(self):
        self.assertIn('no corresponde una interpretación clínica',
                      generate_report({**PATIENT,'no_btps':True},SESSION,records(),references=refs))
        excluded=records()
        for row in excluded:row['review_status']='excluded'
        self.assertIn('No hay maniobras seleccionadas',self.report(excluded))
        original=deepcopy(excluded)
        self.report(excluded)
        self.assertEqual(excluded,original)


if __name__=='__main__':unittest.main()
