import os
import tempfile
from typing import Optional

from fastapi import FastAPI, File, HTTPException, UploadFile
from faster_whisper import WhisperModel

from app.db import db_init, save_normalized_entry, save_raw_hive_log
from app.services import build_legacy_preview, ollama_extract, utc_now_sql

# Configuration
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base")  # base/small for CPU MVP
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cpu")
WHISPER_COMPUTE = os.getenv("WHISPER_COMPUTE", "int8")


# App bootstrap
app = FastAPI(title="Yard Assistant MVP")
whisper = WhisperModel(WHISPER_MODEL, device=WHISPER_DEVICE, compute_type=WHISPER_COMPUTE)

db_init()


# API routes
@app.get("/health")
def health():
    return {"ok": True}


@app.post("/api/voice")
@app.post("/voice")
def voice(file: UploadFile = File(...)):
    """Transcribe audio, extract structured data, and persist raw + normalized records."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    # Endpoint stays sync because Whisper + requests + sqlite are blocking.
    tmp_path: Optional[str] = None
    try:
        suffix = os.path.splitext(file.filename)[1] or ".bin"
        # Use a unique temporary path instead of trusting client filename.
        with tempfile.NamedTemporaryFile(mode="wb", suffix=suffix, delete=False) as tmp_file:
            tmp_path = tmp_file.name
            tmp_file.write(file.file.read())

        segments, info = whisper.transcribe(tmp_path, beam_size=1)
        transcript = " ".join([seg.text.strip() for seg in segments]).strip()
        if not transcript:
            raise HTTPException(status_code=400, detail="Could not transcribe audio")

        created_at_sql = utc_now_sql()
        extracted = ollama_extract(transcript, created_at_sql)
        if not extracted.inspection.raw_transcript:
            extracted.inspection.raw_transcript = transcript

        parsed_json = extracted.model_dump_json(exclude_none=False)
        hive_id = extracted.hive.hive_id or "UNKNOWN"

        # Mandatory raw audit write before best-effort normalized write.
        row_id = save_raw_hive_log(
            created_at=created_at_sql,
            hive_id=hive_id,
            parsed_json=parsed_json,
            raw_transcript=transcript,
        )

        try:
            save_normalized_entry(extracted)
        except Exception as exc:
            print(f"[WARN] Normalized insert failed for hive_log_id={row_id}: {exc}")

        return {
            "id": row_id,
            "preview": build_legacy_preview(extracted, transcript, created_at_sql),
        }
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception as exc:
                print(f"[WARN] Failed to remove temp audio file {tmp_path}: {exc}")
