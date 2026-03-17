import os
import tempfile
import csv
import io
from typing import Optional

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from faster_whisper import WhisperModel

from app.db import (
    DB_PATH,
    db_init,
    export_all_data_json,
    export_hive_dashboard_csv_rows,
    get_hive,
    list_hive_dashboard,
    list_hive_inspections,
    list_recent_inspections,
    list_recent_logs,
    save_normalized_entry,
    save_raw_hive_log,
)
from app.services import build_legacy_preview, ollama_extract, utc_now_sql

# Configuration
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base")  # base/small for CPU MVP
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cpu")
WHISPER_COMPUTE = os.getenv("WHISPER_COMPUTE", "int8")
BASE_DIR = os.path.dirname(__file__)


# App bootstrap
app = FastAPI(title="Yard Assistant MVP")
whisper = WhisperModel(WHISPER_MODEL, device=WHISPER_DEVICE, compute_type=WHISPER_COMPUTE)
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")

db_init()


# Web routes
@app.get("/")
def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/hives")
def hives_page(request: Request):
    dashboard_rows = list_hive_dashboard()
    return templates.TemplateResponse("hives.html", {"request": request, "hives": dashboard_rows})


@app.get("/hives/{hive_id}")
def hive_detail_page(request: Request, hive_id: str):
    hive = get_hive(hive_id)
    inspections = list_hive_inspections(hive_id)
    return templates.TemplateResponse(
        "hive_detail.html",
        {"request": request, "hive": hive, "hive_id": hive_id, "inspections": inspections},
    )


@app.get("/inspections")
def inspections_page(request: Request):
    inspections = list_recent_inspections()
    return templates.TemplateResponse("inspections.html", {"request": request, "inspections": inspections})


@app.get("/transcripts")
def transcripts_page(request: Request):
    logs = list_recent_logs()
    return templates.TemplateResponse("transcripts.html", {"request": request, "logs": logs})


@app.get("/voice")
def voice_page(request: Request):
    return templates.TemplateResponse("voice.html", {"request": request})


# API routes
@app.get("/health")
def health():
    return {"ok": True}


@app.get("/export/json")
def export_json():
    payload = export_all_data_json()
    return JSONResponse(
        content=payload,
        headers={"Content-Disposition": 'attachment; filename="yard-assistant-export.json"'},
    )


@app.get("/export/csv")
def export_csv():
    rows = export_hive_dashboard_csv_rows()
    headers = [
        "hive_id",
        "name",
        "inspected_at",
        "beekeeper_strength",
        "reserves_estimate",
        "queen_seen",
        "recommended_action",
        "strength_score",
        "food_score",
        "swarm_risk",
        "queen_status",
        "confidence",
    ]

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=headers)
    writer.writeheader()
    for row in rows:
        writer.writerow({key: row.get(key) for key in headers})

    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="yard-assistant-hives.csv"'},
    )


@app.get("/export/sqlite")
def export_sqlite():
    if not os.path.exists(DB_PATH):
        raise HTTPException(status_code=404, detail=f"SQLite database file not found at {DB_PATH}")
    return FileResponse(DB_PATH, filename="yard-assistant.sqlite", media_type="application/octet-stream")


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
