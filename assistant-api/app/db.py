import os
import sqlite3
from typing import Any

from app.schemas import HiveData, HiveInspectionPayload, InspectionData, MetricsData

# Configuration
DB_PATH = os.getenv("DB_PATH", "/data/logbook.sqlite")
SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.sql")


# Database helpers

def get_conn() -> sqlite3.Connection:
    """Create a SQLite connection with foreign-key enforcement enabled."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def db_init() -> None:
    """Initialize database schema from schema.sql if tables/views are missing."""
    db_dir = os.path.dirname(DB_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        schema_sql = f.read()

    conn = get_conn()
    try:
        conn.executescript(schema_sql)
        conn.commit()
    finally:
        conn.close()


def save_raw_hive_log(created_at: str, hive_id: str, parsed_json: str, raw_transcript: str) -> int:
    """Persist mandatory raw audit record; returns hive_logs row id."""
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO hive_logs (created_at, hive_id, data_json, raw_transcript) VALUES (?, ?, ?, ?)",
            (created_at, hive_id, parsed_json, raw_transcript),
        )
        conn.commit()
        row_id = cur.lastrowid
    finally:
        conn.close()

    if row_id is None:
        raise RuntimeError("Failed to insert entry into hive_logs.")
    return row_id


def upsert_hive(conn: sqlite3.Connection, hive: HiveData) -> None:
    hive_id = hive.hive_id or "UNKNOWN"
    conn.execute(
        """
        INSERT INTO hives (hive_id, name, hive_type, location, notes)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(hive_id) DO UPDATE SET
            name = COALESCE(excluded.name, hives.name),
            hive_type = COALESCE(excluded.hive_type, hives.hive_type),
            location = COALESCE(excluded.location, hives.location),
            notes = COALESCE(excluded.notes, hives.notes)
        """,
        (hive_id, hive.name, hive.hive_type, hive.location, hive.notes),
    )


def create_inspection(conn: sqlite3.Connection, hive_id: str, inspection: InspectionData) -> int:
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO inspections (
            hive_id,
            inspected_at,
            temperature_c,
            days_since_last_inspection,
            inspection_type,
            flight_activity,
            pollen_intake,
            behavior,
            weight_class,
            dead_bees_front,
            trend_flight,
            trend_weight,
            bee_streets,
            bee_covered_frames,
            brood_frames,
            open_brood,
            capped_brood,
            brood_pattern,
            queen_seen,
            eggs_seen,
            honey_frames,
            reserves_estimate,
            pollen_frames,
            honey_bands,
            free_space,
            queen_cells,
            swarm_signs,
            super_added,
            foundation_added,
            varroa_level,
            deformed_bees,
            diarrhea,
            humidity_issue,
            beekeeper_strength,
            ready_for_flow,
            ready_for_winter,
            recommended_action,
            note,
            raw_transcript
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            hive_id,
            inspection.inspected_at,
            inspection.temperature_c,
            inspection.days_since_last_inspection,
            inspection.inspection_type or "brzi",
            inspection.flight_activity,
            inspection.pollen_intake,
            inspection.behavior,
            inspection.weight_class,
            inspection.dead_bees_front,
            inspection.trend_flight,
            inspection.trend_weight,
            inspection.bee_streets,
            inspection.bee_covered_frames,
            inspection.brood_frames,
            inspection.open_brood,
            inspection.capped_brood,
            inspection.brood_pattern,
            inspection.queen_seen,
            inspection.eggs_seen,
            inspection.honey_frames,
            inspection.reserves_estimate,
            inspection.pollen_frames,
            inspection.honey_bands,
            inspection.free_space,
            inspection.queen_cells,
            inspection.swarm_signs,
            inspection.super_added,
            inspection.foundation_added,
            inspection.varroa_level,
            inspection.deformed_bees,
            inspection.diarrhea,
            inspection.humidity_issue,
            inspection.beekeeper_strength,
            inspection.ready_for_flow,
            inspection.ready_for_winter,
            inspection.recommended_action,
            inspection.note,
            inspection.raw_transcript,
        ),
    )

    inspection_id = cur.lastrowid
    if inspection_id is None:
        raise RuntimeError("Failed to create inspection.")
    return inspection_id


def create_inspection_metrics(conn: sqlite3.Connection, inspection_id: int, metrics: MetricsData) -> None:
    conn.execute(
        """
        INSERT INTO inspection_metrics (
            inspection_id,
            strength_score,
            bagrem_readiness,
            food_score,
            swarm_risk,
            queen_status,
            confidence,
            actions_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            inspection_id,
            metrics.strength_score,
            metrics.bagrem_readiness,
            metrics.food_score,
            metrics.swarm_risk,
            metrics.queen_status,
            metrics.confidence,
            metrics.actions_json,
        ),
    )


def save_normalized_entry(payload: HiveInspectionPayload) -> None:
    """Persist normalized records in one transaction (hive + inspection + metrics)."""
    conn = get_conn()
    try:
        upsert_hive(conn, payload.hive)
        hive_id = payload.hive.hive_id or "UNKNOWN"
        inspection_id = create_inspection(conn, hive_id, payload.inspection)
        create_inspection_metrics(conn, inspection_id, payload.metrics)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def list_hives(limit: int = 200) -> list[dict[str, Any]]:
    conn = get_conn()
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT
                hive_id,
                name,
                hive_type,
                location,
                notes,
                created_at
            FROM hives
            ORDER BY hive_id ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def list_hive_dashboard(limit: int = 200) -> list[dict[str, Any]]:
    conn = get_conn()
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT
                hive_id,
                name,
                inspected_at,
                beekeeper_strength,
                reserves_estimate,
                queen_seen,
                recommended_action
            FROM v_hive_latest
            ORDER BY hive_id ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def get_hive(hive_id: str) -> dict[str, Any] | None:
    conn = get_conn()
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            """
            SELECT
                hive_id,
                name,
                hive_type,
                location,
                notes,
                created_at
            FROM hives
            WHERE hive_id = ?
            """,
            (hive_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def list_hive_inspections(hive_id: str, limit: int = 50) -> list[dict[str, Any]]:
    conn = get_conn()
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT
                i.inspection_id,
                i.hive_id,
                i.inspected_at,
                i.inspection_type,
                i.beekeeper_strength,
                i.reserves_estimate,
                i.recommended_action,
                i.note,
                m.strength_score,
                m.bagrem_readiness,
                m.food_score,
                m.swarm_risk,
                m.queen_status,
                m.confidence
            FROM inspections i
            LEFT JOIN inspection_metrics m
                ON m.inspection_id = i.inspection_id
            WHERE i.hive_id = ?
            ORDER BY i.inspected_at DESC
            LIMIT ?
            """,
            (hive_id, limit),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def list_recent_inspections(limit: int = 200) -> list[dict[str, Any]]:
    conn = get_conn()
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT
                i.inspection_id,
                i.hive_id,
                h.name AS hive_name,
                i.inspected_at,
                i.inspection_type,
                i.beekeeper_strength,
                i.reserves_estimate,
                i.recommended_action,
                i.note,
                m.strength_score,
                m.food_score,
                m.swarm_risk,
                m.queen_status,
                m.confidence
            FROM inspections i
            LEFT JOIN hives h
                ON h.hive_id = i.hive_id
            LEFT JOIN inspection_metrics m
                ON m.inspection_id = i.inspection_id
            ORDER BY i.inspected_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def list_recent_logs(limit: int = 200) -> list[dict[str, Any]]:
    conn = get_conn()
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT
                id,
                created_at,
                hive_id,
                raw_transcript,
                data_json
            FROM hive_logs
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()
