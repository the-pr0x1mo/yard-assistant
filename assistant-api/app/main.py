import os
import json
import sqlite3
from datetime import datetime, timezone
from typing import Optional

import requests
from fastapi import FastAPI, UploadFile, File, HTTPException
from pydantic import BaseModel, Field
from faster_whisper import WhisperModel


OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:3b")
DB_PATH = os.getenv("DB_PATH", "/data/logbook.sqlite")
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base")  # base/small for CPU MVP
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cpu")
WHISPER_COMPUTE = os.getenv("WHISPER_COMPUTE", "int8")
SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.sql")

app = FastAPI(title="Yard Assistant MVP")

# Whisper init (CPU)
whisper = WhisperModel(WHISPER_MODEL, device=WHISPER_DEVICE, compute_type=WHISPER_COMPUTE)


class HiveLogEntry(BaseModel):
    hive_id: str = Field(..., description="e.g. H1, H2")
    strength: Optional[str] = Field(None, description="weak/medium/strong or 1-5")
    brood: Optional[str] = Field(None, description="none/some/a lot")
    stores: Optional[str] = Field(None, description="low/medium/high")
    actions_taken: Optional[str] = None
    notes: Optional[str] = None

    raw_transcript: str
    created_at: str


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def db_init() -> None:
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


def map_beekeeper_strength(strength: Optional[str]) -> Optional[str]:
    if not strength:
        return None

    value = strength.strip().lower()
    mapping = {
        "weak": "slabo",
        "medium": "srednje",
        "strong": "jako",
        "very_strong": "veoma_jako",
        "veoma_jako": "veoma_jako",
        "jako": "jako",
        "srednje": "srednje",
        "slabo": "slabo",
        "1": "slabo",
        "2": "srednje",
        "3": "srednje",
        "4": "jako",
        "5": "veoma_jako",
    }
    return mapping.get(value)


def to_score_from_strength(strength: Optional[str]) -> Optional[float]:
    if not strength:
        return None

    value = strength.strip().lower()
    numeric_map = {
        "1": 20.0,
        "2": 40.0,
        "3": 60.0,
        "4": 80.0,
        "5": 95.0,
        "weak": 30.0,
        "medium": 60.0,
        "strong": 85.0,
        "veoma_jako": 95.0,
        "jako": 85.0,
        "srednje": 60.0,
        "slabo": 30.0,
    }
    return numeric_map.get(value)


def to_food_score(stores: Optional[str]) -> Optional[float]:
    if not stores:
        return None

    value = stores.strip().lower()
    mapping = {
        "low": 25.0,
        "medium": 60.0,
        "high": 90.0,
        "nisko": 25.0,
        "srednje": 60.0,
        "dovoljno": 80.0,
        "visak": 95.0,
    }
    return mapping.get(value)


def ensure_hive(conn: sqlite3.Connection, hive_id: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO hives (hive_id) VALUES (?)",
        (hive_id,),
    )


def create_inspection(conn: sqlite3.Connection, entry: HiveLogEntry) -> int:
    beekeeper_strength = map_beekeeper_strength(entry.strength)
    inspected_at = entry.created_at.replace("T", " ").split("+")[0]

    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO inspections (
            hive_id,
            inspected_at,
            inspection_type,
            beekeeper_strength,
            note,
            raw_transcript
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            entry.hive_id,
            inspected_at,
            "brzi",
            beekeeper_strength,
            entry.notes,
            entry.raw_transcript,
        ),
    )

    inspection_id = cur.lastrowid
    if inspection_id is None:
        raise RuntimeError("Failed to create inspection.")
    return inspection_id


def create_inspection_metrics(conn: sqlite3.Connection, inspection_id: int, entry: HiveLogEntry) -> None:
    strength_score = to_score_from_strength(entry.strength)
    food_score = to_food_score(entry.stores)
    bagrem_readiness = None
    if strength_score is not None and food_score is not None:
        bagrem_readiness = round((strength_score * 0.7) + (food_score * 0.3), 1)

    non_empty_fields = sum(
        [
            1 if entry.hive_id and entry.hive_id != "UNKNOWN" else 0,
            1 if entry.strength else 0,
            1 if entry.brood else 0,
            1 if entry.stores else 0,
        ]
    )
    if non_empty_fields >= 3:
        confidence = "high"
    elif non_empty_fields == 2:
        confidence = "med"
    else:
        confidence = "low"

    actions_json = None
    if entry.actions_taken:
        actions_json = json.dumps({"actions_taken": entry.actions_taken}, ensure_ascii=True)

    conn.execute(
        """
        INSERT INTO inspection_metrics (
            inspection_id,
            strength_score,
            bagrem_readiness,
            food_score,
            confidence,
            actions_json
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            inspection_id,
            strength_score,
            bagrem_readiness,
            food_score,
            confidence,
            actions_json,
        ),
    )


def save_raw_hive_log(entry: HiveLogEntry) -> int:
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO hive_logs (created_at, hive_id, data_json, raw_transcript) VALUES (?, ?, ?, ?)",
            (entry.created_at, entry.hive_id, entry.model_dump_json(), entry.raw_transcript),
        )
        conn.commit()
        row_id = cur.lastrowid
    finally:
        conn.close()

    if row_id is None:
        raise RuntimeError("Failed to insert entry into hive_logs.")
    return row_id


def save_normalized_entry(entry: HiveLogEntry) -> None:
    conn = get_conn()
    try:
        ensure_hive(conn, entry.hive_id)
        inspection_id = create_inspection(conn, entry)
        create_inspection_metrics(conn, inspection_id, entry)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


db_init()


def ollama_extract(transcript: str) -> HiveLogEntry:
    """
    Use Ollama to extract structured fields from transcript.
    MVP: simple JSON instruction; we validate with Pydantic.
    """
    now = datetime.now(timezone.utc).isoformat()
    system = (
        "You are a structured data extractor for beehive inspection notes. "
        "Respond ONLY with structured data."
        "Do not add explanations."
        "Return ONLY valid JSON with keys: hive_id, strength, brood, stores, actions_taken, notes. "
        "If a field is unknown, use null. hive_id is required; if missing, set hive_id to 'UNKNOWN'."
    )
    prompt = f"{system}\nTranscript:\n{transcript}"

    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
    }
    r = requests.post(f"{OLLAMA_BASE_URL}/api/generate", json=payload, timeout=120)
    r.raise_for_status()
    text = r.json().get("response", "").strip()

    # Try parse JSON from model output
    try:
        data = json.loads(text)
    except Exception:
        # fallback: wrap into notes only
        data = {
            "hive_id": "UNKNOWN",
            "notes": transcript,
            "strength": None,
            "brood": None,
            "stores": None,
            "actions_taken": None,
        }

    entry = HiveLogEntry(
        hive_id=data.get("hive_id") or "UNKNOWN",
        strength=data.get("strength"),
        brood=data.get("brood"),
        stores=data.get("stores"),
        actions_taken=data.get("actions_taken"),
        notes=data.get("notes"),
        raw_transcript=transcript,
        created_at=now,
    )
    return entry


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/api/voice")
@app.post("/voice")
async def voice(file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    # Save temp audio
    tmp_path = f"/tmp/{file.filename}"
    content = await file.read()
    with open(tmp_path, "wb") as f:
        f.write(content)

    # Transcribe
    segments, info = whisper.transcribe(tmp_path, beam_size=1)
    transcript = " ".join([seg.text.strip() for seg in segments]).strip()
    if not transcript:
        raise HTTPException(status_code=400, detail="Could not transcribe audio")

    # Extract structured data
    entry = ollama_extract(transcript)

    # Always preserve raw audit trail first.
    row_id = save_raw_hive_log(entry)

    # Best-effort normalized writes; keep MVP response contract.
    try:
        save_normalized_entry(entry)
    except Exception as exc:
        print(f"[WARN] Normalized insert failed for hive_log_id={row_id}: {exc}")

    return {
        "id": row_id,
        "preview": entry.model_dump(),
    }
