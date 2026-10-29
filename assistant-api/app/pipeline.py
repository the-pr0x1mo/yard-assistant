"""Orchestration starts with an already committed source record."""
import json
import logging
import sqlite3
from time import perf_counter

from app import db
from app.schemas import ExtractionError, HiveInspectionPayload, InspectionData
from app.services import build_preview, ollama_extract

logger = logging.getLogger(__name__)


def response_for_log(log_id):
    log = db.get_log(log_id)
    inspection = db.get_inspection_for_log(log_id)
    completed = inspection is not None and log["normalization_status"] == "completed"
    preview = {"raw_transcript": log["raw_transcript"], "created_at": log["created_at"], "structured": None}
    if completed:
        # Use persisted facts, not an uncommitted model candidate.
        payload = HiveInspectionPayload.model_validate({
            "hive": {"hive_id": inspection["hive_id"]},
            "inspection": {key: inspection[key] for key in InspectionData.model_fields},
        })
        preview = build_preview(payload, log["raw_transcript"], log["created_at"])
    failed = log["extraction_status"] == "failed" or log["normalization_status"] == "failed"
    return {"id": log_id, "status": "completed" if completed else "failed" if failed else "pending",
            "extraction_status": log["extraction_status"], "normalization_status": log["normalization_status"],
            "inspection_id": inspection["inspection_id"] if inspection else None,
            "confirmation_status": inspection["confirmation_status"] if inspection else None,
            "error": {"code": log["error_code"], "message": log["error_message"]} if log["error_code"] else None,
            "preview": preview}


def process_log(log_id):
    started = perf_counter()
    attempt_id = db.start_attempt(log_id)
    if attempt_id is None:
        return response_for_log(log_id)
    extraction_status = "failed"
    phase = "extraction"
    persistence_ms = 0.0
    try:
        log = db.get_log(log_id)
        result = ollama_extract(log["raw_transcript"])
        extraction_status = result.status
        phase = "extraction_persistence"
        saving = perf_counter()
        db.record_extraction(log_id, attempt_id, result)
        persistence_ms += (perf_counter() - saving) * 1000
        if result.status == "completed" and result.payload is not None:
            phase = "normalization"
            saving = perf_counter()
            db.save_normalized_entry(log_id, attempt_id, result.payload)
            persistence_ms += (perf_counter() - saving) * 1000
        else:
            error = result.error or ExtractionError(code="internal_error", message="Extraction did not produce a payload")
            db.fail_attempt(log_id, attempt_id, error.code, error.message)
    except Exception as exc:
        # No transcript, response, filesystem path or connection configuration in logs.
        code = "normalization_persistence_error" if phase == "normalization" else (
            "persistence_error" if isinstance(exc, sqlite3.Error) else "internal_error")
        logger.error(json.dumps({"event": "pipeline_failure", "log_id": log_id,
                                 "attempt_id": attempt_id, "error_code": code, "exception_type": type(exc).__name__}))
        try:
            db.fail_attempt(log_id, attempt_id, code, "Processing failed; original transcript is saved",
                            extraction_status=extraction_status,
                            normalization_status="failed" if extraction_status == "completed" else "pending")
        except Exception:
            # Disk/connection can fail again. Do not claim the status update was persisted.
            return {"id": log_id, "status": "failed", "extraction_status": extraction_status,
                    "normalization_status": "failed", "inspection_id": None, "preview": None,
                    "error": {"code": "status_persistence_error", "message":
                              "Original transcript was saved; processing status could not be updated. Check database storage."}}
    response = response_for_log(log_id)
    logger.info(json.dumps({"event": "pipeline", "log_id": log_id, "attempt_id": attempt_id,
                            "status": response["status"], "persistence_ms": round(persistence_ms, 3),
                            "duration_ms": round((perf_counter() - started) * 1000, 3)}))
    return response
