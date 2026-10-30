"""Explicit development database operations. Nothing here runs on app startup."""
import argparse
import json
import os
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

from app import db
from app.schemas import ExtractionResult, ReviewConfirmation
from app.services import parse_payload

SEED_TRANSCRIPT = """Društvo broj 1. Stanju košnici mirno,
matica vidjena, 4 rama sa leglom,
ima zatvorenog legla, ima larvi,
ima sveže zasijanog, 5 ramova
sa medom. Pogača pojedena do pola."""
SEED_FACTS = {"hive": {"hive_id": "H1"}, "inspection": {
    "behavior": "mirne", "queen_seen": 1, "brood_frames": 4, "open_brood": 1,
    "capped_brood": 1, "honey_frames": 5, "eggs_seen": None,
    "note": "Ima sveže zasijanog. Pogača pojedena do pola."}}


def seed():
    db.check_schema()
    if db.query("SELECT COUNT(*) AS n FROM hive_logs")[0]["n"]:
        raise RuntimeError("Seed requires an empty database; nothing changed")
    fixture_time = "2026-01-15 10:00:00"
    payload = parse_payload(json.dumps(SEED_FACTS, ensure_ascii=False), SEED_TRANSCRIPT)
    result = ExtractionResult(status="completed", payload=payload,
                              model_response=json.dumps(SEED_FACTS, ensure_ascii=False),
                              metadata={"source": "synthetic_seed", "model": "fixture", "prompt_version": "hive_semantics_v2"})
    approved = ReviewConfirmation(review_token="synthetic", inspected_at=fixture_time,
        hive={"hive_id": "H1", "create": True}, inspection=payload.inspection)
    inspection_id = db.save_review({"review_id": "synthetic-seed", "transcript": SEED_TRANSCRIPT,
        "created_at": fixture_time, "whisper_metadata": {"source": "synthetic_seed"},
        "extraction": result.model_dump()}, approved)
    log_id = db.query("SELECT raw_log_id FROM inspections WHERE inspection_id=?", (inspection_id,))[0]["raw_log_id"]
    # Make fixture exports reproducible, including operational timestamps.
    with db.connection() as conn:
        conn.execute("UPDATE hives SET created_at=?", (fixture_time,))
        conn.execute("UPDATE inspections SET created_at=?, confirmed_at=?", (fixture_time, fixture_time))
        conn.execute("UPDATE extraction_attempts SET started_at=?, finished_at=?", (fixture_time, fixture_time))
    return log_id


def reset_database(backup):
    path = Path(db.DB_PATH).resolve()
    backup = Path(backup).resolve()
    if not path.is_file():
        raise RuntimeError("Database does not exist; use init")
    if backup.exists() or backup == path:
        raise RuntimeError("Backup destination must be a new file")
    # User must stop the API first. Keep original data in a consistent SQLite backup.
    backup.parent.mkdir(parents=True, exist_ok=True)
    db.backup_database(backup)
    # Resolve/checkpoint any old WAL before atomically replacing the main database.
    with closing(sqlite3.connect(path)) as old:
        checkpoint = old.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        if checkpoint[0] != 0:
            raise RuntimeError("Database is busy; stop the API before resetting")
        mode = old.execute("PRAGMA journal_mode=DELETE").fetchone()[0]
        if mode != "delete":
            raise RuntimeError("Could not leave WAL mode; reset aborted")
    with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".sqlite", delete=False) as tmp:
        fresh = Path(tmp.name)
    try:
        with closing(sqlite3.connect(fresh)) as conn:
            conn.executescript(db.SCHEMA_PATH.read_text(encoding="utf-8"))
        os.replace(fresh, path)
    finally:
        fresh.unlink(missing_ok=True)


def cleanup_audio(backup):
    """Explicit logical removal, after verifying a consistent full database backup."""
    db.check_schema()
    backup = Path(backup).resolve()
    if backup.exists() or backup == Path(db.DB_PATH).resolve():
        raise RuntimeError("Backup destination must be a new file")
    db.backup_database(backup)
    with db.connection() as source:
        source.execute("BEGIN IMMEDIATE")
        with closing(sqlite3.connect(backup.as_uri() + "?mode=ro", uri=True)) as saved:
            if saved.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                raise RuntimeError("Backup integrity verification failed; audio unchanged")
            if saved.execute("PRAGMA foreign_key_check").fetchall():
                raise RuntimeError("Backup foreign key verification failed; audio unchanged")
            source_schema = [tuple(r) for r in source.execute("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY name")]
            if source_schema != saved.execute("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY name").fetchall():
                raise RuntimeError("Backup schema verification failed; audio unchanged")
            for table in ('hives', 'hive_logs', 'extraction_attempts', 'inspections', 'sqlite_sequence'):
                original = [tuple(r) for r in source.execute(f"SELECT * FROM {table} ORDER BY rowid")]
                if original != saved.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall():
                    raise RuntimeError("Database changed since backup; stop API and retry with a new backup")
            if saved.execute("PRAGMA user_version").fetchone()[0] != db.SCHEMA_VERSION:
                raise RuntimeError("Backup version verification failed; audio unchanged")
        count = source.execute("UPDATE hive_logs SET audio_bytes=NULL, audio_content_type=NULL WHERE audio_bytes IS NOT NULL OR audio_content_type IS NOT NULL").rowcount
    return count


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", help="Explicit database file (overrides DB_PATH/DATABASE_PATH)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="Initialize empty schema or verify compatible existing schema")
    sub.add_parser("seed", help="Seed deterministic synthetic fixture; requires empty database")
    sub.add_parser("check", help="Read-only schema check")
    backup = sub.add_parser("backup", help="Create consistent SQLite snapshot")
    backup.add_argument("destination")
    reset = sub.add_parser("reset", help="Replace synthetic database after backing it up; API must be stopped")
    reset.add_argument("--confirm-delete-synthetic-data", action="store_true", required=True)
    reset.add_argument("--api-stopped", action="store_true", required=True)
    reset.add_argument("--backup", required=True)
    recover = sub.add_parser("recover-pending", help="Mark interrupted attempts failed; API must be stopped")
    recover.add_argument("--api-stopped", action="store_true", required=True)
    cleanup = sub.add_parser("cleanup-audio", help="Back up, verify and remove existing audio BLOB values only")
    cleanup.add_argument("--api-stopped", action="store_true", required=True)
    cleanup.add_argument("--confirm-remove-audio", action="store_true", required=True)
    cleanup.add_argument("--backup", required=True)
    args = parser.parse_args(argv)
    if args.db:
        db.DB_PATH = args.db
    try:
        if args.command == "init":
            db.db_init()
        elif args.command == "check":
            db.check_schema()
        elif args.command == "seed":
            seed()
        elif args.command == "reset":
            reset_database(args.backup)
        elif args.command == "recover-pending":
            db.check_schema()
            print(f"Recovered {db.recover_pending()} interrupted attempts")
        elif args.command == "cleanup-audio":
            print(f"Removed audio from {cleanup_audio(args.backup)} logs; verified backup: {args.backup}")
        elif args.command == "backup":
            if Path(args.destination).exists():
                raise RuntimeError("Backup destination already exists")
            db.backup_database(args.destination)
    except (RuntimeError, sqlite3.Error) as exc:
        parser.exit(1, f"{exc}\n")
    print(f"{args.command}: complete")


if __name__ == "__main__":
    main()
