# Data model

See [YA-01: pipeline and persistence](ya-01.md#pipeline-and-persistence) for the
current schema v2, lifecycle and statuses. The authoritative DDL is
[`schema.sql`](../assistant-api/app/schema.sql).

- `hive_logs`: immutable source audio/transcript, server timestamp, Whisper metadata
  and processing status.
- `extraction_attempts`: linked request attempts, model response, validated payload,
  error/status and performance metadata. One pending attempt per source.
- `hives`: canonical identity and factual descriptive metadata.
- `inspections`: factual observations, unique source/attempt linkage, application
  timestamp and separate human confirmation status.
- `v_hive_latest`: latest inspection per hive, using inspection ID to break ties.

No scoring/metrics table exists in the clean schema. Legacy synthetic databases
are not migrated automatically. Use an explicitly initialized new file or the
[backed-up development reset](ya-01.md#local-setup-and-tests).

Facts are immutable after persistence in this version. Confirmation records review;
field correction history is deferred. Raw records and prior attempts are never
replaced by reprocessing.
