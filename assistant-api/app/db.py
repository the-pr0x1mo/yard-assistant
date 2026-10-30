"""SQLite lifecycle, audit records and atomic normalized persistence."""
import base64
import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from app.schemas import ExtractionResult, HiveInspectionPayload, InspectionData
from app.services import utc_now_sql

# DB_PATH takes precedence; accept the previously documented DATABASE_PATH alias.
DB_PATH = os.getenv("DB_PATH") or os.getenv("DATABASE_PATH") or "/data/logbook.sqlite"
SCHEMA_PATH = Path(__file__).with_name("schema.sql")
SCHEMA_VERSION = 2


@contextmanager
def connection(*, readonly=False):
    path = Path(DB_PATH).resolve().as_uri()
    conn = sqlite3.connect(f"{path}?mode={'ro' if readonly else 'rw'}", uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def check_schema():
    try:
        with connection(readonly=True) as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version != SCHEMA_VERSION:
                raise RuntimeError(f"Database schema {version} is incompatible; expected {SCHEMA_VERSION}. "
                                   "See docs/ya-01.md for explicit initialization/reset.")
    except sqlite3.OperationalError as exc:
        raise RuntimeError("Database not initialized. Run python -m app.db_cli init; see docs/ya-01.md") from exc


def db_init():
    """Explicit, repeatable initializer; refuses populated/unversioned databases."""
    path = Path(DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        if tables:
            check_schema()
            return
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    finally:
        conn.close()


def query(sql, args=()):
    with connection(readonly=True) as conn:
        return [dict(row) for row in conn.execute(sql, args).fetchall()]


def save_raw_hive_log(transcript, *, created_at=None, audio_bytes=None, audio_content_type=None, metadata=None):
    with connection() as conn:
        cur = conn.execute(
            """INSERT INTO hive_logs(created_at, raw_transcript, audio_bytes,
               audio_content_type, whisper_metadata_json) VALUES (?, ?, ?, ?, ?)""",
            (created_at or utc_now_sql(), transcript, audio_bytes, audio_content_type,
             json.dumps(metadata or {}, ensure_ascii=False)),
        )
        return cur.lastrowid


def get_log(log_id):
    rows = query("SELECT id, created_at, raw_transcript, extraction_status, normalization_status, "
                 "error_code, error_message, whisper_metadata_json FROM hive_logs WHERE id=?", (log_id,))
    if not rows:
        raise KeyError(log_id)
    return rows[0]


class ProcessingBusy(Exception):
    pass


def start_attempt(log_id):
    with connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        if not conn.execute("SELECT id FROM hive_logs WHERE id=?", (log_id,)).fetchone():
            raise KeyError(log_id)
        if conn.execute("SELECT inspection_id FROM inspections WHERE raw_log_id=?", (log_id,)).fetchone():
            return None  # Already normalized: return the existing inspection, never overwrite it.
        if conn.execute("SELECT 1 FROM extraction_attempts WHERE raw_log_id=? AND status='pending'", (log_id,)).fetchone():
            raise ProcessingBusy(log_id)
        cur = conn.execute("INSERT INTO extraction_attempts(raw_log_id,started_at) VALUES (?,?)", (log_id, utc_now_sql()))
        conn.execute("UPDATE hive_logs SET extraction_status='pending', normalization_status='pending', "
                     "error_code=NULL, error_message=NULL WHERE id=?", (log_id,))
        return cur.lastrowid


def record_extraction(log_id, attempt_id, result: ExtractionResult):
    with connection() as conn:
        conn.execute("""UPDATE extraction_attempts SET extraction_status=?, model_response=?, payload_json=?,
                     metadata_json=? WHERE attempt_id=? AND raw_log_id=?""",
                     (result.status, result.model_response,
                      result.payload.model_dump_json() if result.payload else None,
                      json.dumps(result.metadata), attempt_id, log_id))
        conn.execute("UPDATE hive_logs SET extraction_status=? WHERE id=?", (result.status, log_id))


def fail_attempt(log_id, attempt_id, code, message, *, extraction_status="failed", normalization_status="pending"):
    with connection() as conn:
        conn.execute("""UPDATE extraction_attempts SET status='failed', extraction_status=?,
                     normalization_status=?, finished_at=?, error_code=?, error_message=? WHERE attempt_id=?""",
                     (extraction_status, normalization_status, utc_now_sql(), code, message, attempt_id))
        conn.execute("UPDATE hive_logs SET extraction_status=?, normalization_status=?, error_code=?, error_message=? WHERE id=?",
                     (extraction_status, normalization_status, code, message, log_id))


def create_inspection(conn, log_id, attempt_id, payload, created_at):
    """Field names come exclusively from the validated contract, never user SQL."""
    facts = payload.inspection.model_dump()
    columns = ["raw_log_id", "extraction_attempt_id", "hive_id", "inspected_at", *facts]
    values = [log_id, attempt_id, payload.hive.hive_id, created_at, *facts.values()]
    sql = f"INSERT INTO inspections ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})"
    return conn.execute(sql, values).lastrowid


def save_normalized_entry(log_id, attempt_id, payload: HiveInspectionPayload):
    with connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        log = conn.execute("SELECT * FROM hive_logs WHERE id=?", (log_id,)).fetchone()
        attempt = conn.execute("SELECT * FROM extraction_attempts WHERE attempt_id=? AND raw_log_id=?",
                               (attempt_id, log_id)).fetchone()
        if not attempt or attempt["status"] != "pending" or attempt["extraction_status"] != "completed":
            raise RuntimeError("Attempt is not ready for normalization")
        hive = payload.hive
        conn.execute("""INSERT INTO hives(hive_id,name,hive_type,location,notes) VALUES (?,?,?,?,?)
                     ON CONFLICT(hive_id) DO NOTHING""",
                     (hive.hive_id, hive.name, hive.hive_type, hive.location, hive.notes))
        inspection_id = create_inspection(conn, log_id, attempt_id, payload, log["created_at"])
        conn.execute("""UPDATE extraction_attempts SET status='completed', normalization_status='completed',
                     finished_at=? WHERE attempt_id=?""", (utc_now_sql(), attempt_id))
        conn.execute("""UPDATE hive_logs SET normalization_status='completed', error_code=NULL,
                     error_message=NULL WHERE id=?""", (log_id,))
        return inspection_id


def get_inspection_for_log(log_id):
    rows = query("SELECT * FROM inspections WHERE raw_log_id=?", (log_id,))
    return rows[0] if rows else None


def confirm_inspection(inspection_id):
    with connection() as conn:
        cur = conn.execute("UPDATE inspections SET confirmation_status='confirmed', confirmed_at=COALESCE(confirmed_at,?) "
                           "WHERE inspection_id=?", (utc_now_sql(), inspection_id))
        if not cur.rowcount:
            raise KeyError(inspection_id)


def list_hive_dashboard(limit=200):
    return query("SELECT * FROM v_hive_latest ORDER BY hive_id LIMIT ?", (limit,))


def get_hive(hive_id):
    rows = query("SELECT * FROM hives WHERE hive_id=?", (hive_id,))
    return rows[0] if rows else None


def list_hive_inspections(hive_id, limit=50):
    return query("SELECT * FROM inspections WHERE hive_id=? ORDER BY inspected_at DESC, inspection_id DESC LIMIT ?", (hive_id, limit))


def list_recent_inspections(limit=200):
    return query("SELECT i.*, h.name AS hive_name FROM inspections i LEFT JOIN hives h USING(hive_id) "
                 "ORDER BY inspected_at DESC, inspection_id DESC LIMIT ?", (limit,))


def list_recent_logs(limit=200):
    return query("""SELECT l.id, l.created_at, l.raw_transcript, l.extraction_status, l.normalization_status,
                 l.error_code, l.error_message, i.hive_id, i.inspection_id, i.confirmation_status,
                 a.payload_json AS data_json FROM hive_logs l
                 LEFT JOIN inspections i ON i.raw_log_id=l.id
                 LEFT JOIN extraction_attempts a ON a.attempt_id=(
                   SELECT MAX(attempt_id) FROM extraction_attempts WHERE raw_log_id=l.id)
                 ORDER BY l.id DESC LIMIT ?""", (limit,))


def export_all_data_json():
    with connection(readonly=True) as conn:
        conn.execute("BEGIN")  # One consistent snapshot across all tables.
        data = {table: [dict(r) for r in conn.execute(f"SELECT * FROM {table} ORDER BY {key}")]
                for table, key in (("hives", "hive_id"), ("inspections", "inspection_id"),
                                   ("hive_logs", "id"), ("extraction_attempts", "attempt_id"))}
        for log in data["hive_logs"]:
            audio = log.pop("audio_bytes")
            log["audio_base64"] = base64.b64encode(audio).decode("ascii") if audio is not None else None
        return {"schema_version": SCHEMA_VERSION, **data}


# Preserve legacy latest-hive CSV columns; removed analytical values are empty.
DASHBOARD_CSV_FIELDS = ["hive_id", "name", "inspected_at", "beekeeper_strength", "reserves_estimate",
                        "queen_seen", "recommended_action", "strength_score", "food_score",
                        "swarm_risk", "queen_status", "confidence"]
INSPECTION_CSV_FIELDS = ["inspection_id", "raw_log_id", "extraction_attempt_id", "hive_id", "inspected_at",
                         *InspectionData.model_fields,
                         "confirmation_status", "confirmed_at", "extraction_status", "normalization_status"]


def export_hive_dashboard_csv_rows():
    return query("SELECT * FROM v_hive_latest ORDER BY hive_id")


def export_inspection_csv_rows():
    return query("SELECT i.*, l.extraction_status, l.normalization_status FROM inspections i "
                 "JOIN hive_logs l ON l.id=i.raw_log_id ORDER BY inspection_id")


def get_stats_summary():
    return {"total_hives": query("SELECT COUNT(*) AS n FROM hives")[0]["n"],
            "total_inspections": query("SELECT COUNT(*) AS n FROM inspections")[0]["n"],
            "failed_logs": query("SELECT COUNT(*) AS n FROM hive_logs WHERE extraction_status='failed' OR normalization_status='failed'")[0]["n"],
            "unreviewed": query("SELECT COUNT(*) AS n FROM inspections WHERE confirmation_status='unreviewed'")[0]["n"]}


def backup_database(destination):
    """SQLite backup API includes committed WAL content and produces a consistent file."""
    with connection(readonly=True) as source:
        target = sqlite3.connect(destination)
        try:
            source.backup(target)
        finally:
            target.close()


def recover_pending():
    """Operator command only, after stopping the API. Never invoked at startup."""
    with connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        rows = conn.execute("SELECT * FROM extraction_attempts WHERE status='pending'").fetchall()
        for row in rows:
            extraction = row["extraction_status"]
            if extraction == "pending":
                extraction = "failed"
            normalization = "failed" if extraction == "completed" else "pending"
            conn.execute("""UPDATE extraction_attempts SET status='failed', extraction_status=?,
                         normalization_status=?, finished_at=?, error_code='interrupted',
                         error_message='Processing interrupted; ready for reprocessing' WHERE attempt_id=?""",
                         (extraction, normalization, utc_now_sql(), row["attempt_id"]))
            conn.execute("""UPDATE hive_logs SET extraction_status=?, normalization_status=?,
                         error_code='interrupted', error_message='Processing interrupted; ready for reprocessing' WHERE id=?""",
                         (extraction, normalization, row["raw_log_id"]))
        return len(rows)
