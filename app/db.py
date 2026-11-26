import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime

from app.paths import ensure_user_data_dir


DB_PATH = ensure_user_data_dir() / "espirometro.sqlite3"


@contextmanager
def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS patients (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                last_name TEXT NOT NULL,
                first_name TEXT NOT NULL,
                dni TEXT UNIQUE,
                birth_date TEXT,
                sex TEXT,
                ethnicity TEXT,
                height_cm REAL,
                weight_kg REAL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                patient_id INTEGER NOT NULL REFERENCES patients(id),
                created_at TEXT NOT NULL,
                calibration_date TEXT,
                height_cm REAL,
                weight_kg REAL,
                notes TEXT
            );

            CREATE TABLE IF NOT EXISTS maneuvers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL REFERENCES sessions(id),
                created_at TEXT NOT NULL,
                accepted INTEGER NOT NULL DEFAULT 0,
                review_status TEXT NOT NULL DEFAULT 'pending',
                phase TEXT NOT NULL DEFAULT 'pre',
                print_selected INTEGER NOT NULL DEFAULT 0,
                pef REAL,
                fvc REAL,
                fev1 REAL,
                fev1_fvc REAL,
                fef2575 REAL,
                duration REAL,
                bev REAL,
                eofe_ok INTEGER,
                quality_errors_json TEXT,
                samples_json TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value TEXT
            );
            """
        )
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(patients)")}
        if "dni" not in columns:
            conn.execute("ALTER TABLE patients ADD COLUMN dni TEXT")
        if "ethnicity" not in columns:
            conn.execute("ALTER TABLE patients ADD COLUMN ethnicity TEXT")
        if "no_btps" not in columns:
            conn.execute("ALTER TABLE patients ADD COLUMN no_btps INTEGER NOT NULL DEFAULT 0")
        session_columns = {row["name"] for row in conn.execute("PRAGMA table_info(sessions)")}
        if "height_cm" not in session_columns:
            conn.execute("ALTER TABLE sessions ADD COLUMN height_cm REAL")
        if "weight_kg" not in session_columns:
            conn.execute("ALTER TABLE sessions ADD COLUMN weight_kg REAL")
        maneuver_columns = {row["name"] for row in conn.execute("PRAGMA table_info(maneuvers)")}
        if "review_status" not in maneuver_columns:
            conn.execute("ALTER TABLE maneuvers ADD COLUMN review_status TEXT NOT NULL DEFAULT 'pending'")
            conn.execute("UPDATE maneuvers SET review_status = 'accepted' WHERE accepted = 1")
        if "phase" not in maneuver_columns:
            conn.execute("ALTER TABLE maneuvers ADD COLUMN phase TEXT NOT NULL DEFAULT 'pre'")
        if "quality_errors_json" not in maneuver_columns:
            conn.execute("ALTER TABLE maneuvers ADD COLUMN quality_errors_json TEXT")
        if "print_selected" not in maneuver_columns:
            conn.execute("ALTER TABLE maneuvers ADD COLUMN print_selected INTEGER NOT NULL DEFAULT 0")
        if "processing_json" not in maneuver_columns:
            conn.execute("ALTER TABLE maneuvers ADD COLUMN processing_json TEXT")
        for table in ('patients', 'sessions'):
            existing = {row['name'] for row in conn.execute(f'PRAGMA table_info({table})')}
            if 'transfer_uid' not in existing:
                conn.execute(f'ALTER TABLE {table} ADD COLUMN transfer_uid TEXT')
            if table == 'sessions' and 'source_json' not in existing:
                conn.execute('ALTER TABLE sessions ADD COLUMN source_json TEXT')
            for row in conn.execute(f'SELECT id FROM {table} WHERE transfer_uid IS NULL').fetchall():
                conn.execute(f'UPDATE {table} SET transfer_uid = ? WHERE id = ?', (str(uuid.uuid4()), row['id']))
            conn.execute(f'CREATE UNIQUE INDEX IF NOT EXISTS idx_{table}_transfer_uid ON {table}(transfer_uid)')
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_patients_dni_unique ON patients(dni)")
        conn.execute("""CREATE TABLE IF NOT EXISTS respiratory_measurements (
            id INTEGER PRIMARY KEY, session_id INTEGER NOT NULL REFERENCES sessions(id),
            kind TEXT NOT NULL CHECK(kind IN ('svc','mvv')), phase TEXT NOT NULL CHECK(phase IN ('pre','post')),
            created_at TEXT NOT NULL, included INTEGER NOT NULL DEFAULT 0 CHECK(included IN (0,1)),
            result_json TEXT NOT NULL, samples_json TEXT NOT NULL)""")


def create_patient(last_name, first_name, dni="", birth_date="", sex="", ethnicity="", height_cm=None, weight_kg=None, no_btps=False):
    with connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO patients(last_name, first_name, dni, birth_date, sex, ethnicity, height_cm, weight_kg, created_at, no_btps)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                last_name,
                first_name,
                dni,
                birth_date,
                sex,
                ethnicity,
                height_cm,
                weight_kg,
                datetime.now().isoformat(timespec="seconds"),
                int(bool(no_btps)),
            ),
        )
        conn.execute('UPDATE patients SET transfer_uid = ? WHERE id = ?', (str(uuid.uuid4()), cur.lastrowid))
        return cur.lastrowid


def list_patients():
    with connect() as conn:
        return conn.execute(
            """
            SELECT
                p.*,
                MAX(s.created_at) AS last_spirometry_at
            FROM patients p
            LEFT JOIN sessions s ON s.patient_id = p.id
            GROUP BY p.id
            ORDER BY p.last_name, p.first_name, p.id
            """
        ).fetchall()


def get_patient(patient_id):
    with connect() as conn:
        return conn.execute("SELECT * FROM patients WHERE id = ?", (patient_id,)).fetchone()


def get_patient_by_dni(dni):
    with connect() as conn:
        return conn.execute("SELECT * FROM patients WHERE dni = ?", (dni,)).fetchone()


def update_patient(patient_id, last_name, first_name, dni, birth_date, sex, ethnicity, no_btps=False):
    with connect() as conn:
        conn.execute(
            """
            UPDATE patients
            SET last_name = ?, first_name = ?, dni = ?, birth_date = ?, sex = ?, ethnicity = ?, no_btps = ?
            WHERE id = ?
            """,
            (last_name, first_name, dni, birth_date, sex, ethnicity, int(bool(no_btps)), patient_id),
        )


def update_patient_anthropometrics(patient_id, height_cm, weight_kg):
    with connect() as conn:
        conn.execute(
            "UPDATE patients SET height_cm = ?, weight_kg = ? WHERE id = ?",
            (height_cm, weight_kg, patient_id),
        )


def update_patient_ethnicity(patient_id, ethnicity):
    with connect() as conn:
        conn.execute(
            "UPDATE patients SET ethnicity = ? WHERE id = ?",
            (ethnicity, patient_id),
        )


def get_setting(key, default=None):
    with connect() as conn:
        row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row is not None else default


def set_setting(key, value):
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO app_settings(key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )


def list_sessions_for_patient(patient_id):
    with connect() as conn:
        return conn.execute(
            """
            SELECT s.*, COUNT(m.id) + (SELECT COUNT(*) FROM respiratory_measurements r WHERE r.session_id=s.id) AS maneuver_count
            FROM sessions s
            LEFT JOIN maneuvers m ON m.session_id = s.id
            WHERE s.patient_id = ?
            GROUP BY s.id
            ORDER BY s.created_at DESC
            """,
            (patient_id,),
        ).fetchall()


def get_session(session_id):
    with connect() as conn:
        return conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()


def update_session_notes(session_id, notes):
    with connect() as conn:
        conn.execute(
            "UPDATE sessions SET notes = ? WHERE id = ?",
            (notes, session_id),
        )


def list_maneuvers_for_session(session_id):
    with connect() as conn:
        return conn.execute(
            """
            SELECT *
            FROM maneuvers
            WHERE session_id = ?
            ORDER BY created_at ASC, id ASC
            """,
            (session_id,),
        ).fetchall()


def create_session(patient_id, calibration_date=None, height_cm=None, weight_kg=None, notes=""):
    from app.reference_policy import configured_selection, snapshot, SETTING
    patient = get_patient(patient_id)
    policy = snapshot(configured_selection(get_setting(SETTING)), patient["ethnicity"])
    with connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO sessions(patient_id, created_at, calibration_date, height_cm, weight_kg, notes, source_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                patient_id,
                datetime.now().isoformat(timespec="seconds"),
                calibration_date,
                height_cm,
                weight_kg,
                notes,
                json.dumps({"origin": "native", "reference_policy": policy}),
            ),
        )
        conn.execute('UPDATE sessions SET transfer_uid = ? WHERE id = ?', (str(uuid.uuid4()), cur.lastrowid))
        return cur.lastrowid


def post_phase_started(session_id):
    with connect() as conn:
        session = conn.execute('SELECT source_json FROM sessions WHERE id=?', (session_id,)).fetchone()
        if session is None:
            return False
        workflow = json.loads(session['source_json'] or '{}').get('workflow', {})
        if isinstance(workflow, dict) and workflow.get('post_started') is True:
            return True
        return conn.execute("""SELECT 1 FROM maneuvers WHERE session_id=? AND phase='post'
            UNION ALL SELECT 1 FROM respiratory_measurements WHERE session_id=? AND phase='post' LIMIT 1""",
            (session_id, session_id)).fetchone() is not None


def begin_post_phase(session_id):
    """Persist the one-way acquisition stage without changing original references."""
    with connect() as conn:
        session = conn.execute('SELECT source_json FROM sessions WHERE id=?', (session_id,)).fetchone()
        if session is None:
            raise ValueError('Estudio no encontrado')
        source = json.loads(session['source_json'] or '{}')
        workflow = source.get('workflow', {})
        workflow = dict(workflow) if isinstance(workflow, dict) else {}
        if workflow.get('post_started') is True:
            return
        workflow['post_started'] = True
        source['workflow'] = workflow
        conn.execute('UPDATE sessions SET source_json=? WHERE id=?',
                     (json.dumps(source, ensure_ascii=False), session_id))


def save_maneuver(session_id, params, samples, review_status="accepted", phase="pre"):
    accepted = review_status == "accepted"
    with connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO maneuvers(
                session_id, created_at, accepted, review_status, phase, pef, fvc, fev1, fev1_fvc,
                fef2575, duration, bev, eofe_ok, quality_errors_json, samples_json, processing_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                datetime.now().isoformat(timespec="seconds"),
                int(accepted),
                review_status,
                phase,
                params.get("pef"),
                params.get("fvc"),
                params.get("fev1"),
                params.get("fev1_fvc"),
                params.get("fef2575"),
                params.get("duracion"),
                params.get("bev"),
                int(params.get("meseta_eofe", False)),
                json.dumps(params.get("calidad_errores", [])),
                json.dumps(samples),
                json.dumps(params),
            ),
        )
        return cur.lastrowid


def update_maneuver_status(maneuver_id, review_status):
    if review_status not in {"pending", "accepted", "excluded", "rejected"}:
        raise ValueError(f"Estado de maniobra invalido: {review_status}")
    with connect() as conn:
        conn.execute(
            """
            UPDATE maneuvers
            SET accepted = ?, review_status = ?
            WHERE id = ?
            """,
            (int(review_status == "accepted"), review_status, maneuver_id),
        )


def set_print_selected(session_id, phase, maneuver_id):
    with connect() as conn:
        conn.execute(
            "UPDATE maneuvers SET print_selected = 0 WHERE session_id = ? AND phase = ?",
            (session_id, phase),
        )
        if maneuver_id is not None:
            conn.execute("UPDATE maneuvers SET print_selected = 1 WHERE id = ?", (maneuver_id,))


def delete_maneuver(maneuver_id):
    with connect() as conn:
        conn.execute("DELETE FROM maneuvers WHERE id = ?", (maneuver_id,))


def delete_excluded_maneuvers(session_id):
    with connect() as conn:
        cur = conn.execute(
            """
            DELETE FROM maneuvers
            WHERE session_id = ? AND review_status != 'accepted'
            """,
            (session_id,),
        )
        return cur.rowcount


def list_recent_maneuvers(limit=50):
    with connect() as conn:
        return conn.execute(
            """
            SELECT m.*, p.last_name, p.first_name
            FROM maneuvers m
            JOIN sessions s ON s.id = m.session_id
            JOIN patients p ON p.id = s.patient_id
            ORDER BY m.created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()


def list_respiratory_measurements(session_id, kind=None):
    with connect() as conn:
        rows=conn.execute('SELECT * FROM respiratory_measurements WHERE session_id=? ORDER BY id', (session_id,)).fetchall()
    return [{**dict(row),'result':json.loads(row['result_json'])} for row in rows if kind is None or row['kind']==kind]


def save_respiratory_measurement(session_id, kind, phase, result, samples):
    if kind not in ('svc','mvv') or phase not in ('pre','post') or result.get('measurement_type')!=kind:
        raise ValueError('Tipo de medición inválido')
    with connect() as conn:
        return conn.execute('INSERT INTO respiratory_measurements(session_id,kind,phase,created_at,included,result_json,samples_json) VALUES (?,?,?,?,0,?,?)',
            (session_id,kind,phase,datetime.now().isoformat(timespec='seconds'),json.dumps(result,allow_nan=False),json.dumps(samples,allow_nan=False))).lastrowid


def include_respiratory_measurement(measurement_id, included):
    with connect() as conn:
        conn.execute('UPDATE respiratory_measurements SET included=? WHERE id=?',(int(bool(included)),measurement_id))


def delete_respiratory_measurement(measurement_id):
    with connect() as conn:
        conn.execute('DELETE FROM respiratory_measurements WHERE id=?',(measurement_id,))


def review_maneuver_quality(maneuver_id, expected_params, decisions):
    """Persist only operator quality decisions; do not rewrite measured values/curves."""
    from app.fvc_quality import apply_decisions, validate_quality
    validate_quality(expected_params)
    with connect() as conn:
        row = conn.execute('SELECT processing_json FROM maneuvers WHERE id=?', (maneuver_id,)).fetchone()
        if row is None:
            raise ValueError('Maniobra no encontrada')
        stored = json.loads(row['processing_json'] or '{}')
        from app.fvc_quality import annotate
        current = stored if stored.get('quality_version') == 1 else annotate(stored)
        if current != json.loads(json.dumps(expected_params)):
            raise ValueError('La evaluación cambió. Volvé a abrir la revisión de calidad.')
        updated = apply_decisions(current, decisions, datetime.now().isoformat(timespec='seconds'))
        conn.execute('UPDATE maneuvers SET processing_json=?, quality_errors_json=? WHERE id=?',
                     (json.dumps(updated), json.dumps(updated['calidad_errores']), maneuver_id))
