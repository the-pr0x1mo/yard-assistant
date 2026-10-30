"""Factual extraction contract. Missing observations are null, never estimates."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.normalization import normalize_hive_id

Count = Annotated[int, Field(strict=True, ge=0)]
Flag = Annotated[int, Field(strict=True, ge=0, le=1)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class HiveData(StrictModel):
    hive_id: str | None
    name: str | None = None
    hive_type: str | None = None
    location: str | None = None
    notes: str | None = None

    @field_validator("hive_id", mode="before")
    @classmethod
    def canonical_id(cls, value):
        return normalize_hive_id(value)


class InspectionData(StrictModel):
    temperature_c: float | None = None
    days_since_last_inspection: Count | None = None
    inspection_type: Literal["spoljni", "brzi", "potpuni"] | None = None
    flight_activity: Annotated[int, Field(strict=True, ge=0, le=5)] | None = None
    pollen_intake: Annotated[int, Field(strict=True, ge=0, le=3)] | None = None
    behavior: Literal["mirne", "nervozne", "pljacka", "sumnjivo"] | None = None
    weight_class: Literal["laka", "srednja", "teska", "vrlo_teska"] | None = None
    dead_bees_front: Literal["0", "malo", "puno"] | None = None
    trend_flight: Literal["raste", "isto", "opada"] | None = None
    trend_weight: Literal["dobija", "isto", "gubi"] | None = None
    bee_streets: Count | None = None
    bee_covered_frames: Count | None = None
    brood_frames: Count | None = None
    open_brood: Flag | None = None
    capped_brood: Flag | None = None
    brood_pattern: Literal["kompaktno", "rastrkano", "sumnjivo"] | None = None
    queen_seen: Flag | None = None
    eggs_seen: Flag | None = None
    honey_frames: Count | None = None
    reserves_estimate: Literal["kriticno", "nisko", "dovoljno", "visak"] | None = None
    pollen_frames: Count | None = None
    honey_bands: Literal["nema", "slabi", "dobri", "jaki"] | None = None
    free_space: Literal["nema", "malo", "dovoljno", "previse"] | None = None
    queen_cells: Literal["nema", "zapoceti", "zatvoreni"] | None = None
    swarm_signs: Flag | None = None
    super_added: Flag | None = None
    foundation_added: Count | None = None
    varroa_level: Literal["nema", "malo", "srednje", "jako"] | None = None
    deformed_bees: Flag | None = None
    diarrhea: Flag | None = None
    humidity_issue: Flag | None = None
    beekeeper_strength: Literal["slabo", "srednje", "jako", "veoma_jako"] | None = None
    actions_taken: str | None = None
    note: str | None = None


class HiveInspectionPayload(StrictModel):
    hive: HiveData
    inspection: InspectionData


class ExtractionError(StrictModel):
    code: str
    message: str


class ExtractionResult(StrictModel):
    status: Literal["pending", "completed", "failed"]
    payload: HiveInspectionPayload | None = None
    error: ExtractionError | None = None
    model_response: str | None = None
    metadata: dict = Field(default_factory=dict)
