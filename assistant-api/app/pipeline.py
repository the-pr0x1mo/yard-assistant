"""Ephemeral extraction reviews. Only explicit confirmation writes inspection facts."""
import base64
import hashlib
import hmac
import json
import os
import secrets
from uuid import uuid4

from app import db
from app.schemas import InspectionData
from app.services import ollama_extract, utc_now_sql

# One-process default: restarting discards outstanding reviews. Multiple workers
# must share an operator-configured secret; the token is signed, not encrypted.
_REVIEW_KEY = os.getenv("REVIEW_SIGNING_KEY", "").encode() or secrets.token_bytes(32)


def sign_review(source):
    encoded = base64.urlsafe_b64encode(json.dumps(source, ensure_ascii=False).encode()).decode()
    signature = hmac.new(_REVIEW_KEY, encoded.encode(), hashlib.sha256).hexdigest()
    return encoded + "." + signature


def read_review(token):
    try:
        encoded, signature = token.rsplit(".", 1)
        expected = hmac.new(_REVIEW_KEY, encoded.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError("Invalid review signature")
        return json.loads(base64.urlsafe_b64decode(encoded))
    except (ValueError, UnicodeError, TypeError) as exc:
        raise ValueError("Review expired or invalid; no data saved") from exc


def build_review(transcript, *, created_at=None, metadata=None, source_log_id=None):
    result = ollama_extract(transcript)
    created_at = created_at or utc_now_sql()
    source = {"review_id": str(uuid4()), "transcript": transcript, "created_at": created_at,
              "whisper_metadata": metadata or {}, "extraction": result.model_dump(),
              "source_log_id": source_log_id}
    structured = result.payload.model_dump() if result.payload else {
        "hive": {"hive_id": None, "name": None}, "inspection": InspectionData().model_dump()}
    return {"id": None, "inspection_id": None, "status": "review",
            "confirmation_status": "unconfirmed", "extraction_status": result.status,
            "normalization_status": "pending", "error": result.error.model_dump() if result.error else None,
            "review_token": sign_review(source), "inspected_at": created_at,
            "preview": {"hive_id": structured["hive"]["hive_id"], "raw_transcript": transcript, "created_at": created_at, "structured": structured}}


def response_for_log(log_id):
    log = db.get_log(log_id)
    inspection = db.get_inspection_for_log(log_id)
    hive = db.get_hive(inspection["hive_id"]) if inspection else None
    failed = log["extraction_status"] == "failed" or log["normalization_status"] == "failed"
    return {"id": log_id, "status": "completed" if inspection else "failed" if failed else "pending",
            "inspection_id": inspection["inspection_id"] if inspection else None,
            "confirmation_status": inspection["confirmation_status"] if inspection else None,
            "extraction_status": log["extraction_status"], "normalization_status": log["normalization_status"],
            "error": {"code": log["error_code"], "message": log["error_message"]} if log["error_code"] else None,
            "preview": {"hive_id": inspection["hive_id"] if inspection else None,
                        "raw_transcript": log["raw_transcript"], "created_at": log["created_at"],
                        "structured": {"hive": hive, "inspection": {k: inspection[k] for k in InspectionData.model_fields}}
                        if inspection else None}}


def process_log(log_id):
    """Explicit legacy-source review; never rewrites an existing inspection."""
    if db.get_inspection_for_log(log_id):
        return response_for_log(log_id)
    log = db.get_log(log_id)
    return build_review(log["raw_transcript"], created_at=log["created_at"],
                        metadata=json.loads(log["whisper_metadata_json"]), source_log_id=log_id)
