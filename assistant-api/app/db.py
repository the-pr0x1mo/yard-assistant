"""SQLite lifecycle and transactional, explicitly approved inspection persistence."""
import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from app.schemas import HiveSelection, InspectionCorrection, InspectionData
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
            (created_at or utc_now_sql(), transcript, None, None,
             json.dumps(metadata or {}, ensure_ascii=False)),
        )
        return cur.lastrowid


def get_log(log_id):
    rows = query("SELECT id, created_at, raw_transcript, extraction_status, normalization_status, "
                 "error_code, error_message, whisper_metadata_json FROM hive_logs WHERE id=?", (log_id,))
    if not rows:
        raise KeyError(log_id)
    return rows[0]


def get_inspection_for_log(log_id):
    rows = query("SELECT * FROM inspections WHERE raw_log_id=?", (log_id,))
    return rows[0] if rows else None


def confirm_inspection(inspection_id, correction=None):
    with connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT * FROM inspections WHERE inspection_id=?", (inspection_id,)).fetchone()
        if not row:
            raise KeyError(inspection_id)
        if row["confirmation_status"] == "confirmed":
            return
        HiveSelection(hive_id=row["hive_id"])
        correction = correction or InspectionCorrection(inspected_at=row["inspected_at"],
            inspection=InspectionData(**{k: row[k] for k in InspectionData.model_fields}))
        facts = {"inspected_at": correction.inspected_at, **correction.inspection.model_dump()}
        conn.execute(f"UPDATE inspections SET {','.join(k+'=?' for k in facts)}, confirmation_status='confirmed', confirmed_at=? WHERE inspection_id=?",
                     [*facts.values(), utc_now_sql(), inspection_id])


def list_hive_dashboard(limit=200):
    return query(APPROVED_DASHBOARD + " ORDER BY h.hive_id LIMIT ?", (limit,))


def get_hive(hive_id):
    rows = query("SELECT * FROM hives WHERE hive_id=?", (hive_id,))
    return rows[0] if rows else None


def list_hive_inspections(hive_id, limit=50):
    return query("SELECT i.*, h.name AS hive_name, l.raw_transcript FROM inspections i JOIN hives h USING(hive_id) JOIN hive_logs l ON l.id=i.raw_log_id WHERE i.hive_id=? AND i.confirmation_status='confirmed' ORDER BY inspected_at DESC, inspection_id DESC LIMIT ?", (hive_id, limit))


def list_recent_inspections(limit=200):
    return query("SELECT i.*, h.name AS hive_name, l.raw_transcript FROM inspections i LEFT JOIN hives h USING(hive_id) JOIN hive_logs l ON l.id=i.raw_log_id "
                 "WHERE i.confirmation_status='confirmed' ORDER BY inspected_at DESC, inspection_id DESC LIMIT ?", (limit,))


def list_recent_logs(limit=200):
    return query("""SELECT l.id, l.created_at, l.raw_transcript, l.extraction_status, l.normalization_status,
                 l.error_code, l.error_message, i.hive_id, i.inspection_id, i.confirmation_status FROM hive_logs l
                 LEFT JOIN inspections i ON i.raw_log_id=l.id
                 ORDER BY l.id DESC LIMIT ?""", (limit,))


def export_all_data_json():
    with connection(readonly=True) as conn:
        conn.execute("BEGIN")  # One consistent snapshot across all tables.
        inspections = [dict(r) for r in conn.execute("SELECT * FROM inspections WHERE confirmation_status='confirmed' ORDER BY inspection_id")]
        logs = [dict(r) for r in conn.execute("SELECT l.* FROM hive_logs l JOIN inspections i ON i.raw_log_id=l.id WHERE i.confirmation_status='confirmed' ORDER BY l.id")]
        for log in logs:
            log.pop("audio_bytes")
            log.pop("audio_content_type")
        attempts = [dict(r) for r in conn.execute("SELECT a.* FROM extraction_attempts a JOIN inspections i ON i.extraction_attempt_id=a.attempt_id WHERE i.confirmation_status='confirmed' ORDER BY a.attempt_id")]
        return {"schema_version": SCHEMA_VERSION, "hives": [dict(r) for r in conn.execute("SELECT * FROM hives ORDER BY hive_id")],
                "inspections": inspections, "hive_logs": logs, "extraction_attempts": attempts}


# Preserve legacy latest-hive CSV columns; removed analytical values are empty.
DASHBOARD_CSV_FIELDS = ["hive_id", "name", "inspected_at", "beekeeper_strength", "reserves_estimate",
                        "queen_seen", "recommended_action", "strength_score", "food_score",
                        "swarm_risk", "queen_status", "confidence"]
INSPECTION_CSV_FIELDS = ["inspection_id", "raw_log_id", "extraction_attempt_id", "hive_id", "inspected_at",
                         *InspectionData.model_fields,
                         "confirmation_status", "confirmed_at", "extraction_status", "normalization_status"]


def export_hive_dashboard_csv_rows():
    return query(APPROVED_DASHBOARD + " ORDER BY h.hive_id")


def export_inspection_csv_rows():
    return query("SELECT i.*, l.extraction_status, l.normalization_status FROM inspections i "
                 "JOIN hive_logs l ON l.id=i.raw_log_id WHERE i.confirmation_status='confirmed' ORDER BY inspection_id")


def get_stats_summary():
    return {"total_hives": query("SELECT COUNT(*) AS n FROM hives")[0]["n"],
            "total_inspections": query("SELECT COUNT(*) AS n FROM inspections WHERE confirmation_status='confirmed'")[0]["n"],
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


# The existing view includes YA-01 unreviewed rows. Filter in application queries
# so no schema/view migration is needed on existing v2 databases.
APPROVED_DASHBOARD = """SELECT h.hive_id, h.name, i.* FROM hives h
LEFT JOIN inspections i ON i.inspection_id=(
 SELECT inspection_id FROM inspections WHERE hive_id=h.hive_id AND confirmation_status='confirmed'
 ORDER BY inspected_at DESC, inspection_id DESC LIMIT 1)"""


class ReviewConflict(ValueError):
    pass


def save_review(source, approved):
    """Serialize idempotency lookup and every approved write in one transaction."""
    with connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute("""SELECT i.inspection_id FROM hive_logs l JOIN inspections i ON i.raw_log_id=l.id
            WHERE json_extract(l.whisper_metadata_json, '$.review_id')=?""", (source["review_id"],)).fetchone()
        if existing:
            return existing[0]
        log_id = source.get("source_log_id")
        if log_id:
            existing = conn.execute("SELECT inspection_id FROM inspections WHERE raw_log_id=?", (log_id,)).fetchone()
            if existing:
                return existing[0]
            log = conn.execute("SELECT raw_transcript FROM hive_logs WHERE id=?", (log_id,)).fetchone()
            if not log or log[0] != source["transcript"]:
                raise ReviewConflict("Original transcript no longer available")
        hive = approved.hive
        exists = conn.execute("SELECT 1 FROM hives WHERE hive_id=?", (hive.hive_id,)).fetchone()
        if hive.create:
            if exists:
                raise ReviewConflict("Hive ID already exists; select the existing hive")
            conn.execute("INSERT INTO hives(hive_id,name) VALUES (?,?)", (hive.hive_id, hive.name))
        elif not exists:
            raise ReviewConflict("Select an existing hive or create a new one")
        elif "name" in hive.model_fields_set:
            conn.execute("UPDATE hives SET name=? WHERE hive_id=?", (hive.name, hive.hive_id))
        extraction = source["extraction"]
        status = extraction["status"]
        error = extraction["error"] or {}
        now = utc_now_sql()
        if not log_id:
            metadata = {**source["whisper_metadata"], "review_id": source["review_id"]}
            log_id = conn.execute("""INSERT INTO hive_logs(created_at,raw_transcript,whisper_metadata_json)
                VALUES (?,?,?)""", (source["created_at"], source["transcript"], json.dumps(metadata))).lastrowid
        conn.execute("""UPDATE hive_logs SET extraction_status=?, normalization_status='completed',
            error_code=?, error_message=? WHERE id=?""", (status, error.get("code"), error.get("message"), log_id))
        attempt_id = conn.execute("""INSERT INTO extraction_attempts(raw_log_id,started_at,finished_at,status,
            extraction_status,normalization_status,model_response,payload_json,metadata_json,error_code,error_message)
            VALUES (?,?,?,?,?,'completed',?,?,?,?,?)""",
            (log_id, source["created_at"], now, status, status, extraction["model_response"],
             json.dumps(extraction["payload"]) if extraction["payload"] else None,
             json.dumps(extraction["metadata"]), error.get("code"), error.get("message"))).lastrowid
        inspection_id = insert_approved(conn, log_id, attempt_id, approved)
        return inspection_id


def insert_approved(conn, log_id, attempt_id, approved):
    facts = approved.inspection.model_dump()
    columns = ["raw_log_id", "extraction_attempt_id", "hive_id", "inspected_at", *facts,
               "confirmation_status", "confirmed_at"]
    values = [log_id, attempt_id, approved.hive.hive_id, approved.inspected_at, *facts.values(), "confirmed", utc_now_sql()]
    return conn.execute(f"INSERT INTO inspections ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})", values).lastrowid


def update_inspection(inspection_id, correction):
    with connection() as conn:
        facts = {"inspected_at": correction.inspected_at, **correction.inspection.model_dump()}
        cur = conn.execute(f"UPDATE inspections SET {','.join(k+'=?' for k in facts)} WHERE inspection_id=? AND confirmation_status='confirmed'",
                           [*facts.values(), inspection_id])
        if not cur.rowcount:
            raise KeyError(inspection_id)


def rename_hive(hive_id, name):
    with connection() as conn:
        if not conn.execute("UPDATE hives SET name=? WHERE hive_id=?", (name, hive_id)).rowcount:
            raise KeyError(hive_id)
