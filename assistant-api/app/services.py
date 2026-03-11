import json
import os
from datetime import datetime, timezone
from typing import Any, Optional

import requests

from app.schemas import HiveData, HiveInspectionPayload, InspectionData, MetricsData

# Configuration
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:3b")


# Prompt and enum constraints
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


# Utility helpers

def utc_now_sql() -> str:
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
    """Normalize timestamp-like inputs into UTC SQL format (YYYY-MM-DD HH:MM:SS)."""
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
    """Extract first valid JSON object from model text output."""
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


# Business logic: extraction and mapping

def default_payload(transcript: str, created_at_sql: str) -> HiveInspectionPayload:
    """Safe fallback payload when extraction/parsing fails."""
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
    """Coerce model output to schema-safe values that satisfy DB constraints."""
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
    """Keep backward-compatible preview fields while including structured output."""
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


def ollama_extract(transcript: str, created_at_sql: str) -> HiveInspectionPayload:
    """Extract and validate a normalized payload from transcript via Ollama."""
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
