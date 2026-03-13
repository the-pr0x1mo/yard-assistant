PRAGMA foreign_keys = ON;

-- Raw audit trail table preserved for MVP compatibility.
CREATE TABLE IF NOT EXISTS hive_logs (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at        TEXT NOT NULL,
  hive_id           TEXT NOT NULL,
  data_json         TEXT NOT NULL,
  raw_transcript    TEXT NOT NULL
);

-- 1) Master tabela: kosnice
CREATE TABLE IF NOT EXISTS hives (
  hive_id           TEXT PRIMARY KEY,
  name              TEXT,
  hive_type         TEXT,
  location          TEXT,
  notes             TEXT,
  created_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 2) Inspekcije
CREATE TABLE IF NOT EXISTS inspections (
  inspection_id      INTEGER PRIMARY KEY AUTOINCREMENT,
  hive_id            TEXT NOT NULL,
  inspected_at       TEXT NOT NULL DEFAULT (datetime('now')),
  temperature_c      REAL,

  days_since_last_inspection INTEGER CHECK (days_since_last_inspection >= 0),

  inspection_type    TEXT NOT NULL
                     CHECK (inspection_type IN ('spoljni','brzi','potpuni')),

  flight_activity    INTEGER CHECK (flight_activity BETWEEN 0 AND 5),
  pollen_intake      INTEGER CHECK (pollen_intake BETWEEN 0 AND 3),
  behavior           TEXT CHECK (behavior IN ('mirne','nervozne','pljacka','sumnjivo')),
  weight_class       TEXT CHECK (weight_class IN ('laka','srednja','teska','vrlo_teska')),
  dead_bees_front    TEXT CHECK (dead_bees_front IN ('0','malo','puno')),

  trend_flight       TEXT CHECK (trend_flight IN ('raste','isto','opada')),
  trend_weight       TEXT CHECK (trend_weight IN ('dobija','isto','gubi')),

  bee_streets        INTEGER CHECK (bee_streets >= 0),
  bee_covered_frames INTEGER CHECK (bee_covered_frames >= 0),
  brood_frames       INTEGER CHECK (brood_frames >= 0),
  open_brood         INTEGER CHECK (open_brood IN (0,1)),
  capped_brood       INTEGER CHECK (capped_brood IN (0,1)),
  brood_pattern      TEXT CHECK (brood_pattern IN ('kompaktno','rastrkano','sumnjivo')),
  queen_seen         INTEGER CHECK (queen_seen IN (0,1)),
  eggs_seen          INTEGER CHECK (eggs_seen IN (0,1)),

  honey_frames       INTEGER CHECK (honey_frames >= 0),
  reserves_estimate  TEXT CHECK (reserves_estimate IN ('kriticno','nisko','dovoljno','visak')),

  pollen_frames      INTEGER CHECK (pollen_frames >= 0),
  honey_bands        TEXT CHECK (honey_bands IN ('nema','slabi','dobri','jaki')),

  free_space         TEXT CHECK (free_space IN ('nema','malo','dovoljno','previse')),
  queen_cells        TEXT CHECK (queen_cells IN ('nema','zapoceti','zatvoreni')),
  swarm_signs        INTEGER CHECK (swarm_signs IN (0,1)),

  super_added        INTEGER CHECK (super_added IN (0,1)),
  foundation_added   INTEGER CHECK (foundation_added >= 0),

  varroa_level       TEXT CHECK (varroa_level IN ('nema','malo','srednje','jako')),

  deformed_bees      INTEGER CHECK (deformed_bees IN (0,1)),
  diarrhea           INTEGER CHECK (diarrhea IN (0,1)),
  humidity_issue     INTEGER CHECK (humidity_issue IN (0,1)),

  beekeeper_strength TEXT CHECK (beekeeper_strength IN ('slabo','srednje','jako','veoma_jako')),
  ready_for_flow     INTEGER CHECK (ready_for_flow IN (0,1)),
  ready_for_winter   INTEGER CHECK (ready_for_winter IN (0,1)),
  recommended_action TEXT CHECK (recommended_action IN ('nista','prihrana','prosirenje','spajanje','kontrola_rojenja','tretman')),
  note               TEXT,

  raw_transcript     TEXT,

  created_at         TEXT NOT NULL DEFAULT (datetime('now')),

  FOREIGN KEY (hive_id) REFERENCES hives(hive_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_inspections_hive_time
  ON inspections (hive_id, inspected_at DESC);

CREATE INDEX IF NOT EXISTS idx_inspections_type_time
  ON inspections (inspection_type, inspected_at DESC);

-- 3) Metrike
CREATE TABLE IF NOT EXISTS inspection_metrics (
  metrics_id         INTEGER PRIMARY KEY AUTOINCREMENT,
  inspection_id      INTEGER NOT NULL UNIQUE,

  strength_score     REAL CHECK (strength_score BETWEEN 0 AND 100),
  bagrem_readiness   REAL CHECK (bagrem_readiness BETWEEN 0 AND 100),
  food_score         REAL CHECK (food_score BETWEEN 0 AND 100),

  swarm_risk         TEXT CHECK (swarm_risk IN ('low','med','high')),
  queen_status       TEXT CHECK (queen_status IN ('ok','suspect','missing','unknown')),
  confidence         TEXT CHECK (confidence IN ('low','med','high')),

  actions_json       TEXT,
  computed_at        TEXT NOT NULL DEFAULT (datetime('now')),

  FOREIGN KEY (inspection_id) REFERENCES inspections(inspection_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_metrics_computed_at
  ON inspection_metrics (computed_at DESC);

-- 4) View: poslednje stanje po kosnici
DROP VIEW IF EXISTS v_hive_latest;
CREATE VIEW IF NOT EXISTS v_hive_latest AS
SELECT
  h.hive_id,
  h.name,
  i.inspection_id,
  i.inspected_at,
  i.days_since_last_inspection,
  i.inspection_type,
  i.beekeeper_strength,
  i.reserves_estimate,
  i.queen_seen,
  i.recommended_action,
  m.strength_score,
  m.bagrem_readiness,
  m.food_score,
  m.swarm_risk,
  m.queen_status,
  m.confidence
FROM hives h
LEFT JOIN inspections i
  ON i.inspection_id = (
    SELECT i2.inspection_id
    FROM inspections i2
    WHERE i2.hive_id = h.hive_id
    ORDER BY i2.inspected_at DESC
    LIMIT 1
  )
LEFT JOIN inspection_metrics m
  ON m.inspection_id = i.inspection_id;

-- 5) View: automatski izracunato vreme od prethodne inspekcije
CREATE VIEW IF NOT EXISTS v_inspections_with_prev_gap AS
SELECT
  i.*,
  CAST(
    julianday(i.inspected_at) -
    julianday((
      SELECT MAX(i2.inspected_at)
      FROM inspections i2
      WHERE i2.hive_id = i.hive_id
        AND i2.inspected_at < i.inspected_at
    ))
    AS INTEGER
  ) AS computed_days_since_previous
FROM inspections i;
