# Data model

The authoritative [schema.sql](../assistant-api/app/schema.sql) remains version 2.
[YA-02](ya-02.md) changes persistence behavior without DDL, new tables, indexes,
views, database paths, or `user_version` changes.

- `hive_logs`: original read-only transcript, Whisper metadata and processing
  status. New logs have NULL audio fields. `whisper_metadata_json.review_id`
  provides idempotency for explicit review confirmation.
- `extraction_attempts`: original extraction outcome, payload, error and metadata,
  inserted only with confirmation. A failed AI attempt can link to a manually
  approved inspection; extraction remains failed, normalization is completed.
- `hives`: immutable exact primary key and editable display name. No delete or
  primary-key rename is exposed; `ON DELETE RESTRICT` remains intact.
- `inspections`: user-approved facts, unique transcript/attempt links, editable
  inspection date, explicit confirmed status and confirmation time. Corrections
  update the same ID; source links, hive reference and transcript remain immutable.
- `v_hive_latest`: unchanged legacy view. Application dashboard/export queries
  independently select the latest confirmed row so old unreviewed data is excluded.

No draft or revision history is stored. Confirmation is one atomic transaction;
a `BEGIN IMMEDIATE` lock covers duplicate detection and all inserts. Existing
YA-01 unreviewed records remain available for manual review and are never
silently confirmed. No automatic migration, initialization, cleanup or reset runs.
