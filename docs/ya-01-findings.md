# YA-01 inspection findings (before implementation)

Verified from the repository:

- `ollama_extract()` catches every request/parse/validation error and returns an
  `UNKNOWN` / `brzi` / low-confidence payload. Callers cannot distinguish failure.
- JSON parsing accepts prose wrapped around objects; sanitization replaces bad
  values with null and invents a quick inspection type.
- The v1 prompt asks for scores, predictions, recommendations and food/strength
  inferences. Pydantic does not enforce the database's numerical bounds.
- `/api/voice` calls Ollama before committing the transcript. It catches normalized
  insertion failures, prints a warning and still reports success.
- Raw logs have no foreign-key relationship to normalized inspections. Retrying
  can insert duplicates. Model responses and processing attempts are not retained.
- Whisper is loaded and schema DDL runs at module import. No automated tests exist.
- The recorder checks only HTTP success. The upload page shows raw JSON.
- CSV exports only the latest hive snapshot, has no Excel BOM and does not escape
  spreadsheet formulas. SQLite export sends the active file without a snapshot.
- Deployment documentation names `DATABASE_PATH`, while code reads `DB_PATH`.

Implementation decision: the user's development-stage clarification supersedes
the original task's legacy migration requirements. Use a versioned clean factual
schema, explicit initialization and a separately confirmed development reset.
Refuse incompatible databases at startup without changing them. Do not access or
reset the deployed database, change Compose infrastructure or deploy from this task.

Runtime Ollama version/model behavior and live data contents have not been inspected.
