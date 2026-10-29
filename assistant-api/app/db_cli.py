"""Explicit development database operations. Nothing here runs on app startup."""
import argparse
import json
import os
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

from app import db
from app.schemas import ExtractionResult
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
    log_id = db.save_raw_hive_log(SEED_TRANSCRIPT, created_at=fixture_time, metadata={"source": "synthetic_seed"})
    attempt_id = db.start_attempt(log_id)
    payload = parse_payload(json.dumps(SEED_FACTS, ensure_ascii=False), SEED_TRANSCRIPT)
    result = ExtractionResult(status="completed", payload=payload,
                              model_response=json.dumps(SEED_FACTS, ensure_ascii=False),
                              metadata={"source": "synthetic_seed", "model": "fixture", "prompt_version": "hive_semantics_v2"})
    db.record_extraction(log_id, attempt_id, result)
    db.save_normalized_entry(log_id, attempt_id, payload)
    # Make fixture exports reproducible, including operational timestamps.
    with db.connection() as conn:
        conn.execute("UPDATE hives SET created_at=?", (fixture_time,))
        conn.execute("UPDATE inspections SET created_at=?", (fixture_time,))
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
        elif args.command == "backup":
            if Path(args.destination).exists():
                raise RuntimeError("Backup destination already exists")
            db.backup_database(args.destination)
    except (RuntimeError, sqlite3.Error) as exc:
        parser.exit(1, f"{exc}\n")
    print(f"{args.command}: complete")


if __name__ == "__main__":
    main()
