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


def db_init():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
      CREATE TABLE IF NOT EXISTS hive_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at TEXT NOT NULL,
        hive_id TEXT NOT NULL,
        data_json TEXT NOT NULL,
        raw_transcript TEXT NOT NULL
      );
    """)
    conn.commit()
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
        "stream": False
    }
    r = requests.post(f"{OLLAMA_BASE_URL}/api/generate", json=payload, timeout=120)
    r.raise_for_status()
    text = r.json().get("response", "").strip()

    # Try parse JSON from model output
    try:
        data = json.loads(text)
    except Exception:
        # fallback: wrap into notes only
        data = {"hive_id": "UNKNOWN", "notes": transcript, "strength": None, "brood": None, "stores": None, "actions_taken": None}

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


def save_entry(entry: HiveLogEntry) -> int:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO hive_logs (created_at, hive_id, data_json, raw_transcript) VALUES (?, ?, ?, ?)",
        (entry.created_at, entry.hive_id, entry.model_dump_json(), entry.raw_transcript),
    )
    conn.commit()
    row_id = cur.lastrowid
    conn.close()
    return row_id


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

    # Save
    row_id = save_entry(entry)

    return {
        "id": row_id,
        "preview": entry.model_dump(),
    }
