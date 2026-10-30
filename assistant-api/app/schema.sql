-- Schema v2: explicit initialization only. No automatic legacy migration.
PRAGMA foreign_keys = ON;
BEGIN IMMEDIATE;
CREATE TABLE hive_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT NOT NULL,
  raw_transcript TEXT NOT NULL CHECK (length(trim(raw_transcript)) > 0),
  audio_bytes BLOB,
  audio_content_type TEXT,
  whisper_metadata_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(whisper_metadata_json)),
  extraction_status TEXT NOT NULL DEFAULT 'pending' CHECK (extraction_status IN ('pending','completed','failed')),
  normalization_status TEXT NOT NULL DEFAULT 'pending' CHECK (normalization_status IN ('pending','completed','failed')),
  error_code TEXT,
  error_message TEXT
);

CREATE TABLE extraction_attempts (
  attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
  raw_log_id INTEGER NOT NULL REFERENCES hive_logs(id),
  started_at TEXT NOT NULL,
  finished_at TEXT,
  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','completed','failed')),
  extraction_status TEXT NOT NULL DEFAULT 'pending' CHECK (extraction_status IN ('pending','completed','failed')),
  normalization_status TEXT NOT NULL DEFAULT 'pending' CHECK (normalization_status IN ('pending','completed','failed')),
  model_response TEXT,
  payload_json TEXT CHECK (payload_json IS NULL OR json_valid(payload_json)),
  metadata_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata_json)),
  error_code TEXT,
  error_message TEXT
);
CREATE UNIQUE INDEX one_active_attempt ON extraction_attempts(raw_log_id) WHERE status = 'pending';

CREATE TABLE hives (
  hive_id           TEXT PRIMARY KEY,
  name              TEXT,
  hive_type         TEXT,
  location          TEXT,
  notes             TEXT,
  created_at        TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 2) Inspekcije
CREATE TABLE inspections (
  inspection_id      INTEGER PRIMARY KEY AUTOINCREMENT,
  raw_log_id         INTEGER NOT NULL UNIQUE REFERENCES hive_logs(id),
  extraction_attempt_id INTEGER NOT NULL UNIQUE REFERENCES extraction_attempts(attempt_id),
  hive_id            TEXT NOT NULL,
  inspected_at       TEXT NOT NULL,
  temperature_c      REAL,

  days_since_last_inspection INTEGER CHECK (days_since_last_inspection >= 0),

  inspection_type    TEXT
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
  actions_taken      TEXT,
  note               TEXT,

  confirmation_status TEXT NOT NULL DEFAULT 'unreviewed'
    CHECK (confirmation_status IN ('unreviewed','confirmed')),
  confirmed_at       TEXT,

  created_at         TEXT NOT NULL DEFAULT (datetime('now')),

  FOREIGN KEY (hive_id) REFERENCES hives(hive_id) ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_inspections_hive_time
  ON inspections (hive_id, inspected_at DESC);

CREATE INDEX IF NOT EXISTS idx_inspections_type_time
  ON inspections (inspection_type, inspected_at DESC);


CREATE VIEW v_hive_latest AS
SELECT h.hive_id, h.name, i.inspection_id, i.raw_log_id, i.inspected_at,
       i.inspection_type, i.beekeeper_strength, i.reserves_estimate,
       i.queen_seen, i.actions_taken, i.confirmation_status
FROM hives h
LEFT JOIN inspections i ON i.inspection_id = (
 SELECT inspection_id FROM inspections WHERE hive_id = h.hive_id
 ORDER BY inspected_at DESC, inspection_id DESC LIMIT 1
);
PRAGMA user_version = 2;
COMMIT;
