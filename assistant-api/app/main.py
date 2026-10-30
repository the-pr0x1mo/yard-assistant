"""HTTP/UI boundary. Startup verifies the schema and never initializes or resets it."""
import csv
import io
import json
import logging
import os
import sqlite3
import tempfile
from contextlib import asynccontextmanager
from functools import lru_cache
from threading import Lock
from time import perf_counter

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.background import BackgroundTask

from app import db
from app.db import (get_hive, get_stats_summary, list_hive_dashboard,
                    list_hive_inspections, list_recent_inspections, list_recent_logs)
from app.pipeline import build_review, process_log, read_review, response_for_log
from app.schemas import HiveRename, InspectionCorrection, ReviewConfirmation
from app.review_fields import LABELS, GROUPS, COMPACT, FLAGS, field_spec

logger = logging.getLogger(__name__)
BASE_DIR = os.path.dirname(__file__)
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base")
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cpu")
WHISPER_COMPUTE = os.getenv("WHISPER_COMPUTE", "int8")
_whisper_load_lock = Lock()


@lru_cache(maxsize=1)
def _load_whisper():
    # Lazy import/loading keeps deterministic tests independent of GPU/model packages.
    from faster_whisper import WhisperModel
    return WhisperModel(WHISPER_MODEL, device=WHISPER_DEVICE, compute_type=WHISPER_COMPUTE)


def get_whisper():
    # lru_cache alone can evaluate the first concurrent calls more than once.
    with _whisper_load_lock:
        return _load_whisper()


@asynccontextmanager
async def lifespan(app):
    db.check_schema()
    logging.basicConfig(level=logging.INFO)
    yield


app = FastAPI(title="Yard Assistant", lifespan=lifespan)
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))
templates.env.globals.update(field_labels=LABELS, field_groups=GROUPS, compact_fields=COMPACT, flag_fields=FLAGS)
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")


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


@app.get("/stats")
def stats_page(request: Request):
    stats = get_stats_summary()
    return templates.TemplateResponse("stats.html", {"request": request, "stats": stats})


@app.get("/health")
def health():
    db.check_schema()
    return {"ok": True, "schema_version": db.SCHEMA_VERSION}


@app.get("/export/json")
def export_json():
    return JSONResponse(content=db.export_all_data_json(),
                        headers={"Content-Disposition": 'attachment; filename="yard-assistant-export.json"'})


def safe_csv_value(value):
    if isinstance(value, str):
        # Whitespace/control prefixes can conceal formula starters in Excel.
        stripped = value
        while stripped and (stripped[0].isspace() or ord(stripped[0]) < 32 or stripped[0] == "\ufeff"):
            stripped = stripped[1:]
        if stripped.startswith(("=", "+", "-", "@")) or value.startswith(("\t", "\r", "\n")):
            return "'" + value
    return value


def csv_response(rows, fields, filename):
    buffer = io.StringIO(newline="")
    buffer.write("\ufeff")  # Excel detects UTF-8 with the BOM.
    writer = csv.DictWriter(buffer, fieldnames=fields)
    writer.writeheader()
    for row in rows:
        writer.writerow({key: safe_csv_value(row.get(key)) for key in fields})
    return StreamingResponse(iter([buffer.getvalue().encode("utf-8")]), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@app.get("/export/csv")
def export_csv():
    return csv_response(db.export_hive_dashboard_csv_rows(), db.DASHBOARD_CSV_FIELDS, "yard-assistant-hives.csv")


@app.get("/export/inspections.csv")
def export_inspections_csv():
    return csv_response(db.export_inspection_csv_rows(), db.INSPECTION_CSV_FIELDS, "yard-assistant-inspections.csv")


@app.get("/export/sqlite")
def export_sqlite():
    # The backup API includes committed WAL content; sending the live file does not.
    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tmp:
        path = tmp.name
    try:
        db.backup_database(path)
        with sqlite3.connect(path) as snapshot:
            snapshot.execute("PRAGMA secure_delete=ON")
            snapshot.execute("UPDATE hive_logs SET audio_bytes=NULL, audio_content_type=NULL")
            snapshot.commit()
            snapshot.execute("VACUUM")
    except Exception:
        os.unlink(path)
        raise
    return FileResponse(path, filename="yard-assistant.sqlite", media_type="application/octet-stream",
                        background=BackgroundTask(os.unlink, path))


def run_saved_log(log_id):
    try:
        result = process_log(log_id)
    except sqlite3.Error:
        return JSONResponse(status_code=503, content={"id": log_id, "status": "failed",
                            "error": {"code": "persistence_error", "message": "Transcript saved; could not start processing"}})
    return result


@app.post("/api/voice")
@app.post("/voice")
def voice(file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")
    started = perf_counter()
    audio = file.file.read(32 * 1024 * 1024 + 1)
    if not audio:
        raise HTTPException(status_code=400, detail="Empty audio upload")
    if len(audio) > 32 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Audio upload exceeds 32 MiB")
    file.file.close()
    # Fixed temporary suffix; uploaded filenames never become filesystem paths.
    with tempfile.NamedTemporaryFile(suffix=".audio") as tmp:
        tmp.write(audio)
        tmp.flush()
        transcribing = perf_counter()
        try:
            segments, info = get_whisper().transcribe(tmp.name, beam_size=1)
            transcript = "".join(seg.text for seg in segments)
        except Exception:
            raise HTTPException(status_code=422, detail="Audio could not be transcribed; no record was saved")
        whisper_ms = (perf_counter() - transcribing) * 1000
    if not transcript.strip():
        raise HTTPException(status_code=400, detail="Could not transcribe audio; no record was saved")
    del audio
    result = build_review(transcript, metadata={"duration_ms": round(whisper_ms, 3),
                          "model": WHISPER_MODEL, "language": getattr(info, "language", None)})
    logger.info(json.dumps({"event": "voice_review", "whisper_ms": round(whisper_ms, 3),
                            "extraction_status": result["extraction_status"],
                            "total_ms": round((perf_counter() - started) * 1000, 3)}))
    return result


@app.get("/api/logs/{log_id}")
def log_detail(log_id: int):
    try:
        result = response_for_log(log_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Transcript not found")
    result["attempts"] = db.query("SELECT * FROM extraction_attempts WHERE raw_log_id=? ORDER BY attempt_id", (log_id,))
    result["inspection"] = db.get_inspection_for_log(log_id)
    return result


@app.get("/logs/{log_id}")
def review_page(request: Request, log_id: int):
    detail = log_detail(log_id)
    return templates.TemplateResponse("review.html", {"request": request, "result": detail})


@app.get("/api/logs/{log_id}/audio")
def source_audio(log_id: int):
    rows = db.query("SELECT audio_bytes FROM hive_logs WHERE id=?", (log_id,))
    if not rows or rows[0]["audio_bytes"] is None:
        raise HTTPException(status_code=404, detail="Source audio unavailable")
    # Attachment/octet-stream avoids serving arbitrary uploaded types as active content.
    return StreamingResponse(iter([rows[0]["audio_bytes"]]), media_type="application/octet-stream",
                             headers={"Content-Disposition": f'attachment; filename="log-{log_id}.audio"'})


@app.post("/api/logs/{log_id}/reprocess")
def reprocess(log_id: int):
    try:
        db.get_log(log_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Transcript not found")
    return run_saved_log(log_id)


@app.post("/api/inspections/{inspection_id}/confirm")
def confirm(inspection_id: int, body: InspectionCorrection | None = None):
    try:
        db.confirm_inspection(inspection_id, body)
    except KeyError:
        raise HTTPException(status_code=404, detail="Inspection not found")
    except ValueError:
        raise HTTPException(status_code=422, detail="Existing inspection has an invalid hive ID or date")
    except sqlite3.Error:
        raise HTTPException(status_code=503, detail="Confirmation failed; retry")
    return {"inspection_id": inspection_id, "confirmation_status": "confirmed"}


@app.get("/api/hives")
def hive_choices():
    return db.query("SELECT hive_id,name FROM hives WHERE upper(hive_id) != 'UNKNOWN' ORDER BY hive_id")


@app.patch("/api/hives/{hive_id}")
def rename(hive_id: str, body: HiveRename):
    try:
        db.rename_hive(hive_id, body.name)
    except KeyError:
        raise HTTPException(status_code=404, detail="Hive not found")
    except sqlite3.Error:
        raise HTTPException(status_code=503, detail="Name could not be saved; retry")
    return db.get_hive(hive_id)


@app.post("/api/reviews/confirm")
def confirm_review(body: ReviewConfirmation):
    try:
        source = read_review(body.review_token)
        inspection_id = db.save_review(source, body)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except sqlite3.Error:
        raise HTTPException(status_code=503, detail="Nothing saved; keep this card open and retry confirmation")
    inspection = db.query("SELECT * FROM inspections WHERE inspection_id=?", (inspection_id,))[0]
    return {"inspection_id": inspection_id, "id": inspection["raw_log_id"], "confirmation_status": "confirmed"}


@app.put("/api/inspections/{inspection_id}")
def correct_inspection(inspection_id: int, body: InspectionCorrection):
    try:
        db.update_inspection(inspection_id, body)
    except KeyError:
        raise HTTPException(status_code=404, detail="Confirmed inspection not found")
    except sqlite3.Error:
        raise HTTPException(status_code=503, detail="Changes could not be saved; keep this card open and retry")
    return db.query("SELECT * FROM inspections WHERE inspection_id=?", (inspection_id,))[0]


@app.get('/api/inspection-fields')
def inspection_fields():
    return field_spec()


@app.middleware("http")
async def no_persistent_review_cache(request: Request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    return response
