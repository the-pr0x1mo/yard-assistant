from typing import Literal, Optional

from pydantic import BaseModel


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
