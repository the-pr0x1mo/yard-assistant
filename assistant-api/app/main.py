import os
import json
import sqlite3
import tempfile
from datetime import datetime, timezone
from typing import Any, Literal, Optional

import requests
from fastapi import FastAPI, UploadFile, File, HTTPException
from pydantic import BaseModel
from faster_whisper import WhisperModel


OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:3b")
DB_PATH = os.getenv("DB_PATH", "/data/logbook.sqlite")
WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base")  # base/small for CPU MVP
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cpu")
WHISPER_COMPUTE = os.getenv("WHISPER_COMPUTE", "int8")
SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.sql")

SEMANTIC_HINTS = """[You are a Serbian beekeeper inspection data extractor.

Your task is to read one spoken hive inspection transcript, usually in Serbian, and convert it into structured JSON for a beehive logging database.

The transcript may contain:
- informal beekeeper language
- shorthand observations
- speech-to-text mistakes
- incomplete notes
- mixed Serbian and English words

You must interpret meaning conservatively and return only valid JSON.

GENERAL RULES

1. Be tolerant of ASR / speech-to-text mistakes.
Examples:
- "ulica pčela", "ulice pčela", "ulice pcele" may all mean "ulice pčela"
- "unospolena", "unos polena", "limunospolena" may refer to "unos polena"
- "matca", "matica", "matica" may all refer to queen
- "pogaču", "pogacu", "pogača" are equivalent

2. Prefer Serbian enum values exactly as required by the schema.

3. If a field is not mentioned or cannot be inferred safely, use null.

4. Do not invent numbers unless the transcript strongly implies them.

5. If transcript mentions multiple hives, extract the primary hive being described. If not possible, set hive_id to "UNKNOWN" and mention ambiguity in inspection.note.

6. Return ONLY valid JSON. No explanations. No markdown. No code fences.

HIVE IDENTIFICATION

- "prva košnica" -> hive_id = "H1"
- "druga košnica" -> hive_id = "H2"
- "treća košnica" -> hive_id = "H3"
- "četvrta košnica" -> hive_id = "H4"
- "peta košnica" -> hive_id = "H5"
- If hive cannot be identified confidently -> hive_id = "UNKNOWN"

INSPECTION TYPE

- only external observations, flight, pollen, entrance activity -> inspection_type = "spoljni"
- quick check / brief open inspection -> inspection_type = "brzi"
- detailed full internal inspection -> inspection_type = "potpuni"

EXTERNAL OBSERVATIONS

flight_activity:
- no flight -> 0
- "slab let", "lete polako", "izlaze polagano" -> 1
- weak-moderate flight -> 2
- "srednji let", "umeren let" -> 3
- strong flight -> 4
- "jak let", "masovno izleću", "odličan let" -> 5

pollen_intake:
- none -> 0
- "slab unos polena" -> 1
- "umeren unos polena", "srednji unos polena" -> 2
- "jak unos polena", "dobar unos polena" -> 3

behavior:
- "mirne" -> "mirne"
- "nervozne" -> "nervozne"
- "pljačka", "grabež" -> "pljacka"
- suspicious, unusual -> "sumnjivo"

weight_class:
- "laka" -> "laka"
- "srednja" -> "srednja"
- "teška" -> "teska"
- "vrlo teška" -> "vrlo_teska"

dead_bees_front:
- none -> "0"
- few -> "malo"
- many -> "puno"

TRENDS

trend_flight:
- improving -> "raste"
- unchanged -> "isto"
- worsening -> "opada"

trend_weight:
- gaining -> "dobija"
- unchanged -> "isto"
- losing -> "gubi"

COLONY STRENGTH

bee_streets:
- "1 ulica pčela" -> 1
- "2 ulice pčela" -> 2
- "3 ulice pčela" -> 3
- "4 ulice pčela" -> 4
- "5 ulica pčela" -> 5
- if exact count is stated, use it

bee_covered_frames:
- use only if explicitly stated

brood_frames:
- use only if explicitly stated

open_brood:
- explicitly present -> 1
- explicitly absent -> 0

capped_brood:
- explicitly present -> 1
- explicitly absent -> 0

brood_pattern:
- "kompaktno" -> "kompaktno"
- "rastrkano" -> "rastrkano"
- suspicious -> "sumnjivo"

queen_seen:
- queen explicitly seen -> 1
- queen explicitly not seen -> 0
- otherwise null

eggs_seen:
- eggs explicitly seen -> 1
- explicitly none -> 0
- otherwise null

FOOD AND STORES

honey_frames:
- use only if explicitly stated

reserves_estimate:
- critical -> "kriticno"
- low -> "nisko"
- enough -> "dovoljno"
- surplus -> "visak"

Interpretation hints:
- "pojela pogaču", "potrošila pogaču" -> likely "nisko"
- "ima hrane" -> "dovoljno"
- "dosta hrane" -> "dovoljno" or "visak" depending on strength
- "teška košnica" -> likely good reserves
- "laka košnica" -> likely low reserves

pollen_frames:
- use only if clearly mentioned

honey_bands:
- none -> "nema"
- weak -> "slabi"
- good -> "dobri"
- strong -> "jaki"

SPACE AND SWARMING

free_space:
- no space -> "nema"
- little space -> "malo"
- enough space -> "dovoljno"
- too much free space -> "previse"

queen_cells:
- none -> "nema"
- started -> "zapoceti"
- sealed -> "zatvoreni"

swarm_signs:
- present -> 1
- absent -> 0

super_added:
- if super / medišni nastavak added -> 1
- explicitly not added -> 0

foundation_added:
- if number of foundations is known, use number
- if foundations added but number unknown, use null

HEALTH

varroa_level:
- none -> "nema"
- low -> "malo"
- medium -> "srednje"
- high -> "jako"

deformed_bees:
- yes -> 1
- no -> 0

diarrhea:
- yes -> 1
- no -> 0

humidity_issue:
- yes -> 1
- no -> 0

BEEKEEPER SUMMARY

beekeeper_strength:
- "slabo društvo" -> "slabo"
- "srednje društvo" -> "srednje"
- "jako društvo" -> "jako"
- "veoma jako", "prejako" -> "veoma_jako"

Interpret streets approximately:
- 1-2 bee streets -> "slabo"
- 3-4 bee streets -> "srednje"
- 5-6 bee streets -> "jako"
- 7+ bee streets -> "veoma_jako"

ready_for_flow:
- yes -> 1
- no -> 0

ready_for_winter:
- yes -> 1
- no -> 0

recommended_action:
Must be one of:
- "nista"
- "prihrana"
- "prosirenje"
- "spajanje"
- "kontrola_rojenja"
- "tretman"

Examples:
- low food -> "prihrana"
- no space / needs room -> "prosirenje"
- very weak colony -> "spajanje"
- swarm signs -> "kontrola_rojenja"
- varroa / disease concern -> "tretman"

DEAD HIVE RULE

If the hive is clearly dead / collapsed / gone:
- mention this in inspection.note
- beekeeper_strength = "slabo"
- ready_for_flow = 0
- ready_for_winter = 0
- do not invent brood/queen details
- recommended_action may be null unless obvious

METRICS

Estimate only if supported by evidence.

strength_score:
- 0-100 estimate of colony strength

bagrem_readiness:
- 0-100 estimate of readiness for acacia flow

food_score:
- 0-100 estimate of food reserves

swarm_risk:
- "low", "med", or "high"

queen_status:
- "ok", "suspect", "missing", or "unknown"

confidence:
- "low", "med", or "high"
based on how much usable information exists

actions_json:
- JSON string or null
- include extracted beekeeper actions if present, for example feeding or adding space

OUTPUT FORMAT

Return exactly this JSON structure:

{
  "hive": {
    "hive_id": null,
    "name": null,
    "hive_type": null,
    "location": null,
    "notes": null
  },
  "inspection": {
    "inspected_at": null,
    "temperature_c": null,
    "days_since_last_inspection": null,
    "inspection_type": null,
    "flight_activity": null,
    "pollen_intake": null,
    "behavior": null,
    "weight_class": null,
    "dead_bees_front": null,
    "trend_flight": null,
    "trend_weight": null,
    "bee_streets": null,
    "bee_covered_frames": null,
    "brood_frames": null,
    "open_brood": null,
    "capped_brood": null,
    "brood_pattern": null,
    "queen_seen": null,
    "eggs_seen": null,
    "honey_frames": null,
    "reserves_estimate": null,
    "pollen_frames": null,
    "honey_bands": null,
    "free_space": null,
    "queen_cells": null,
    "swarm_signs": null,
    "super_added": null,
    "foundation_added": null,
    "varroa_level": null,
    "deformed_bees": null,
    "diarrhea": null,
    "humidity_issue": null,
    "beekeeper_strength": null,
    "ready_for_flow": null,
    "ready_for_winter": null,
    "recommended_action": null,
    "note": null,
    "raw_transcript": null
  },
  "metrics": {
    "strength_score": null,
    "bagrem_readiness": null,
    "food_score": null,
    "swarm_risk": null,
    "queen_status": null,
    "confidence": null,
    "actions_json": null
  }
}"""

INSPECTION_TYPE_VALUES = {"spoljni", "brzi", "potpuni"}
BEHAVIOR_VALUES = {"mirne", "nervozne", "pljacka", "sumnjivo"}
WEIGHT_CLASS_VALUES = {"laka", "srednja", "teska", "vrlo_teska"}
DEAD_BEES_FRONT_VALUES = {"0", "malo", "puno"}
TREND_FLIGHT_VALUES = {"raste", "isto", "opada"}
TREND_WEIGHT_VALUES = {"dobija", "isto", "gubi"}
BROOD_PATTERN_VALUES = {"kompaktno", "rastrkano", "sumnjivo"}
RESERVES_VALUES = {"kriticno", "nisko", "dovoljno", "visak"}
HONEY_BANDS_VALUES = {"nema", "slabi", "dobri", "jaki"}
FREE_SPACE_VALUES = {"nema", "malo", "dovoljno", "previse"}
QUEEN_CELLS_VALUES = {"nema", "zapoceti", "zatvoreni"}
VARROA_VALUES = {"nema", "malo", "srednje", "jako"}
BEEKEEPER_STRENGTH_VALUES = {"slabo", "srednje", "jako", "veoma_jako"}
RECOMMENDED_ACTION_VALUES = {"nista", "prihrana", "prosirenje", "spajanje", "kontrola_rojenja", "tretman"}
SWARM_RISK_VALUES = {"low", "med", "high"}
QUEEN_STATUS_VALUES = {"ok", "suspect", "missing", "unknown"}
CONFIDENCE_VALUES = {"low", "med", "high"}


app = FastAPI(title="Yard Assistant MVP")

# Whisper init (CPU)
whisper = WhisperModel(WHISPER_MODEL, device=WHISPER_DEVICE, compute_type=WHISPER_COMPUTE)


class HiveData(BaseModel):
    hive_id: Optional[str] = None
    name: Optional[str] = None
    hive_type: Optional[str] = None
    location: Optional[str] = None
    notes: Optional[str] = None


class InspectionData(BaseModel):
    inspected_at: Optional[str] = None
    temperature_c: Optional[float] = None
    days_since_last_inspection: Optional[int] = None
    inspection_type: Optional[Literal["spoljni", "brzi", "potpuni"]] = None
    flight_activity: Optional[int] = None
    pollen_intake: Optional[int] = None
    behavior: Optional[Literal["mirne", "nervozne", "pljacka", "sumnjivo"]] = None
    weight_class: Optional[Literal["laka", "srednja", "teska", "vrlo_teska"]] = None
    dead_bees_front: Optional[Literal["0", "malo", "puno"]] = None
    trend_flight: Optional[Literal["raste", "isto", "opada"]] = None
    trend_weight: Optional[Literal["dobija", "isto", "gubi"]] = None
    bee_streets: Optional[int] = None
    bee_covered_frames: Optional[int] = None
    brood_frames: Optional[int] = None
    open_brood: Optional[int] = None
    capped_brood: Optional[int] = None
    brood_pattern: Optional[Literal["kompaktno", "rastrkano", "sumnjivo"]] = None
    queen_seen: Optional[int] = None
    eggs_seen: Optional[int] = None
    honey_frames: Optional[int] = None
    reserves_estimate: Optional[Literal["kriticno", "nisko", "dovoljno", "visak"]] = None
    pollen_frames: Optional[int] = None
    honey_bands: Optional[Literal["nema", "slabi", "dobri", "jaki"]] = None
    free_space: Optional[Literal["nema", "malo", "dovoljno", "previse"]] = None
    queen_cells: Optional[Literal["nema", "zapoceti", "zatvoreni"]] = None
    swarm_signs: Optional[int] = None
    super_added: Optional[int] = None
    foundation_added: Optional[int] = None
    varroa_level: Optional[Literal["nema", "malo", "srednje", "jako"]] = None
    deformed_bees: Optional[int] = None
    diarrhea: Optional[int] = None
    humidity_issue: Optional[int] = None
    beekeeper_strength: Optional[Literal["slabo", "srednje", "jako", "veoma_jako"]] = None
    ready_for_flow: Optional[int] = None
    ready_for_winter: Optional[int] = None
    recommended_action: Optional[Literal["nista", "prihrana", "prosirenje", "spajanje", "kontrola_rojenja", "tretman"]] = None
    note: Optional[str] = None
    raw_transcript: Optional[str] = None


class MetricsData(BaseModel):
    strength_score: Optional[float] = None
    bagrem_readiness: Optional[float] = None
    food_score: Optional[float] = None
    swarm_risk: Optional[Literal["low", "med", "high"]] = None
    queen_status: Optional[Literal["ok", "suspect", "missing", "unknown"]] = None
    confidence: Optional[Literal["low", "med", "high"]] = None
    actions_json: Optional[str] = None


class HiveInspectionPayload(BaseModel):
    hive: HiveData
    inspection: InspectionData
    metrics: MetricsData


def utc_now_sql() -> str:
    # Store UTC timestamps in SQL-friendly format consistently.
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def canonicalize_text(value: str) -> str:
    return (
        value.strip()
        .lower()
        .replace(" ", "_")
        .replace("-", "_")
        .replace("č", "c")
        .replace("ć", "c")
        .replace("š", "s")
        .replace("ž", "z")
        .replace("đ", "dj")
    )


def normalize_enum(value: Any, allowed: set[str]) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        normalized = canonicalize_text(value)
        if normalized in allowed:
            return normalized
    return None


def normalize_int(value: Any, minimum: Optional[int] = None, maximum: Optional[int] = None) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool):
        candidate = 1 if value else 0
    elif isinstance(value, int):
        candidate = value
    elif isinstance(value, float) and value.is_integer():
        candidate = int(value)
    elif isinstance(value, str):
        raw = value.strip().lower()
        if raw in {"da", "yes", "true"}:
            candidate = 1
        elif raw in {"ne", "no", "false"}:
            candidate = 0
        else:
            try:
                candidate = int(raw)
            except Exception:
                return None
    else:
        return None

    if minimum is not None and candidate < minimum:
        return None
    if maximum is not None and candidate > maximum:
        return None
    return candidate


def normalize_float(value: Any, minimum: Optional[float] = None, maximum: Optional[float] = None) -> Optional[float]:
    if value is None:
        return None
    try:
        candidate = float(value)
    except Exception:
        return None

    if minimum is not None and candidate < minimum:
        return None
    if maximum is not None and candidate > maximum:
        return None
    return candidate


def normalize_timestamp(value: Any) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        return None

    text = value.strip()
    if not text:
        return None

    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        pass

    try:
        dt = datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def normalize_actions_json(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=True)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            parsed = json.loads(text)
            return json.dumps(parsed, ensure_ascii=True)
        except Exception:
            return json.dumps({"actions": text}, ensure_ascii=True)
    return None


def extract_json_object(text: str) -> dict[str, Any]:
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return {}

    snippet = text[start:end + 1]
    try:
        parsed = json.loads(snippet)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def default_payload(transcript: str, created_at_sql: str) -> HiveInspectionPayload:
    return HiveInspectionPayload(
        hive=HiveData(hive_id="UNKNOWN"),
        inspection=InspectionData(
            inspected_at=created_at_sql,
            inspection_type="brzi",
            raw_transcript=transcript,
        ),
        metrics=MetricsData(confidence="low"),
    )


def sanitize_payload(raw: dict[str, Any], transcript: str, created_at_sql: str) -> HiveInspectionPayload:
    hive_raw = raw.get("hive") if isinstance(raw.get("hive"), dict) else {}
    inspection_raw = raw.get("inspection") if isinstance(raw.get("inspection"), dict) else {}
    metrics_raw = raw.get("metrics") if isinstance(raw.get("metrics"), dict) else {}

    hive_id = hive_raw.get("hive_id")
    if isinstance(hive_id, str):
        hive_id = hive_id.strip() or "UNKNOWN"
    else:
        hive_id = "UNKNOWN"

    hive = HiveData(
        hive_id=hive_id,
        name=hive_raw.get("name") if isinstance(hive_raw.get("name"), str) else None,
        hive_type=hive_raw.get("hive_type") if isinstance(hive_raw.get("hive_type"), str) else None,
        location=hive_raw.get("location") if isinstance(hive_raw.get("location"), str) else None,
        notes=hive_raw.get("notes") if isinstance(hive_raw.get("notes"), str) else None,
    )

    inspection = InspectionData(
        inspected_at=normalize_timestamp(inspection_raw.get("inspected_at")) or created_at_sql,
        temperature_c=normalize_float(inspection_raw.get("temperature_c")),
        days_since_last_inspection=normalize_int(inspection_raw.get("days_since_last_inspection"), minimum=0),
        inspection_type=normalize_enum(inspection_raw.get("inspection_type"), INSPECTION_TYPE_VALUES) or "brzi",
        flight_activity=normalize_int(inspection_raw.get("flight_activity"), minimum=0, maximum=5),
        pollen_intake=normalize_int(inspection_raw.get("pollen_intake"), minimum=0, maximum=3),
        behavior=normalize_enum(inspection_raw.get("behavior"), BEHAVIOR_VALUES),
        weight_class=normalize_enum(inspection_raw.get("weight_class"), WEIGHT_CLASS_VALUES),
        dead_bees_front=normalize_enum(inspection_raw.get("dead_bees_front"), DEAD_BEES_FRONT_VALUES),
        trend_flight=normalize_enum(inspection_raw.get("trend_flight"), TREND_FLIGHT_VALUES),
        trend_weight=normalize_enum(inspection_raw.get("trend_weight"), TREND_WEIGHT_VALUES),
        bee_streets=normalize_int(inspection_raw.get("bee_streets"), minimum=0),
        bee_covered_frames=normalize_int(inspection_raw.get("bee_covered_frames"), minimum=0),
        brood_frames=normalize_int(inspection_raw.get("brood_frames"), minimum=0),
        open_brood=normalize_int(inspection_raw.get("open_brood"), minimum=0, maximum=1),
        capped_brood=normalize_int(inspection_raw.get("capped_brood"), minimum=0, maximum=1),
        brood_pattern=normalize_enum(inspection_raw.get("brood_pattern"), BROOD_PATTERN_VALUES),
        queen_seen=normalize_int(inspection_raw.get("queen_seen"), minimum=0, maximum=1),
        eggs_seen=normalize_int(inspection_raw.get("eggs_seen"), minimum=0, maximum=1),
        honey_frames=normalize_int(inspection_raw.get("honey_frames"), minimum=0),
        reserves_estimate=normalize_enum(inspection_raw.get("reserves_estimate"), RESERVES_VALUES),
        pollen_frames=normalize_int(inspection_raw.get("pollen_frames"), minimum=0),
        honey_bands=normalize_enum(inspection_raw.get("honey_bands"), HONEY_BANDS_VALUES),
        free_space=normalize_enum(inspection_raw.get("free_space"), FREE_SPACE_VALUES),
        queen_cells=normalize_enum(inspection_raw.get("queen_cells"), QUEEN_CELLS_VALUES),
        swarm_signs=normalize_int(inspection_raw.get("swarm_signs"), minimum=0, maximum=1),
        super_added=normalize_int(inspection_raw.get("super_added"), minimum=0, maximum=1),
        foundation_added=normalize_int(inspection_raw.get("foundation_added"), minimum=0),
        varroa_level=normalize_enum(inspection_raw.get("varroa_level"), VARROA_VALUES),
        deformed_bees=normalize_int(inspection_raw.get("deformed_bees"), minimum=0, maximum=1),
        diarrhea=normalize_int(inspection_raw.get("diarrhea"), minimum=0, maximum=1),
        humidity_issue=normalize_int(inspection_raw.get("humidity_issue"), minimum=0, maximum=1),
        beekeeper_strength=normalize_enum(inspection_raw.get("beekeeper_strength"), BEEKEEPER_STRENGTH_VALUES),
        ready_for_flow=normalize_int(inspection_raw.get("ready_for_flow"), minimum=0, maximum=1),
        ready_for_winter=normalize_int(inspection_raw.get("ready_for_winter"), minimum=0, maximum=1),
        recommended_action=normalize_enum(inspection_raw.get("recommended_action"), RECOMMENDED_ACTION_VALUES),
        note=inspection_raw.get("note") if isinstance(inspection_raw.get("note"), str) else None,
        raw_transcript=transcript,
    )

    metrics = MetricsData(
        strength_score=normalize_float(metrics_raw.get("strength_score"), minimum=0, maximum=100),
        bagrem_readiness=normalize_float(metrics_raw.get("bagrem_readiness"), minimum=0, maximum=100),
        food_score=normalize_float(metrics_raw.get("food_score"), minimum=0, maximum=100),
        swarm_risk=normalize_enum(metrics_raw.get("swarm_risk"), SWARM_RISK_VALUES),
        queen_status=normalize_enum(metrics_raw.get("queen_status"), QUEEN_STATUS_VALUES),
        confidence=normalize_enum(metrics_raw.get("confidence"), CONFIDENCE_VALUES),
        actions_json=normalize_actions_json(metrics_raw.get("actions_json")),
    )

    return HiveInspectionPayload(hive=hive, inspection=inspection, metrics=metrics)


def build_legacy_preview(payload: HiveInspectionPayload, transcript: str, created_at: str) -> dict[str, Any]:
    brood_preview: Optional[str] = None
    if payload.inspection.brood_frames is not None:
        brood_preview = str(payload.inspection.brood_frames)
    elif payload.inspection.open_brood == 1 or payload.inspection.capped_brood == 1:
        brood_preview = "some"
    elif payload.inspection.open_brood == 0 and payload.inspection.capped_brood == 0:
        brood_preview = "none"

    actions_taken: Optional[str] = None
    if payload.metrics.actions_json:
        try:
            parsed_actions = json.loads(payload.metrics.actions_json)
            if isinstance(parsed_actions, dict):
                actions_taken = parsed_actions.get("actions_taken") or parsed_actions.get("actions")
            if actions_taken is None:
                actions_taken = payload.metrics.actions_json
        except Exception:
            actions_taken = payload.metrics.actions_json

    return {
        "hive_id": payload.hive.hive_id or "UNKNOWN",
        "strength": payload.inspection.beekeeper_strength,
        "brood": brood_preview,
        "stores": payload.inspection.reserves_estimate,
        "actions_taken": actions_taken,
        "notes": payload.inspection.note or payload.hive.notes,
        "raw_transcript": transcript,
        "created_at": created_at,
        "structured": payload.model_dump(),
    }


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


def save_raw_hive_log(created_at: str, hive_id: str, parsed_json: str, raw_transcript: str) -> int:
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


def ollama_extract(transcript: str, created_at_sql: str) -> HiveInspectionPayload:
    """
    Use Ollama to extract a full normalized payload for hive/inspection/metrics.
    Falls back to a safe minimal payload if parsing/validation fails.
    """
    output_shape = {
        "hive": {
            "hive_id": None,
            "name": None,
            "hive_type": None,
            "location": None,
            "notes": None,
        },
        "inspection": {
            "inspected_at": None,
            "temperature_c": None,
            "days_since_last_inspection": None,
            "inspection_type": None,
            "flight_activity": None,
            "pollen_intake": None,
            "behavior": None,
            "weight_class": None,
            "dead_bees_front": None,
            "trend_flight": None,
            "trend_weight": None,
            "bee_streets": None,
            "bee_covered_frames": None,
            "brood_frames": None,
            "open_brood": None,
            "capped_brood": None,
            "brood_pattern": None,
            "queen_seen": None,
            "eggs_seen": None,
            "honey_frames": None,
            "reserves_estimate": None,
            "pollen_frames": None,
            "honey_bands": None,
            "free_space": None,
            "queen_cells": None,
            "swarm_signs": None,
            "super_added": None,
            "foundation_added": None,
            "varroa_level": None,
            "deformed_bees": None,
            "diarrhea": None,
            "humidity_issue": None,
            "beekeeper_strength": None,
            "ready_for_flow": None,
            "ready_for_winter": None,
            "recommended_action": None,
            "note": None,
            "raw_transcript": None,
        },
        "metrics": {
            "strength_score": None,
            "bagrem_readiness": None,
            "food_score": None,
            "swarm_risk": None,
            "queen_status": None,
            "confidence": None,
            "actions_json": None,
        },
    }

    system = (
        f"{SEMANTIC_HINTS}\n\n"
        "Return only one JSON object. Do not return arrays. "
        "Use only enum/int ranges valid for the target SQLite schema. "
        f"Output schema template: {json.dumps(output_shape, ensure_ascii=False)}"
    )
    prompt = f"{system}\n\nTranscript:\n{transcript}"

    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
    }

    try:
        r = requests.post(f"{OLLAMA_BASE_URL}/api/generate", json=payload, timeout=120)
        r.raise_for_status()
        text = r.json().get("response", "").strip()
    except Exception:
        return default_payload(transcript, created_at_sql)

    parsed = extract_json_object(text)
    if not parsed:
        return default_payload(transcript, created_at_sql)

    try:
        return sanitize_payload(parsed, transcript, created_at_sql)
    except Exception:
        return default_payload(transcript, created_at_sql)


db_init()


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/api/voice")
@app.post("/voice")
def voice(file: UploadFile = File(...)):
    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    # Endpoint is sync because downstream work is blocking (Whisper/requests/sqlite).
    tmp_path: Optional[str] = None
    try:
        suffix = os.path.splitext(file.filename)[1] or ".bin"
        # Use a unique temp file path; do not trust raw filename for path construction.
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

        # Raw audit write is mandatory and happens before best-effort normalized writes.
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
