# Life of a voice log

1. Browser uploads audio through `/api/voice` (alias `/voice`).
2. Whisper produces text; the app preserves segment text exactly.
3. SQLite commits the original audio, transcript, application time and Whisper metadata.
4. The app records a pending attempt and calls Ollama once for factual JSON.
5. Pydantic validates the complete response; Python normalizes hive numbering.
6. SQLite commits the model response, validated candidate and metadata.
7. A separate atomic transaction saves hive/inspection and completes processing.
8. The UI reports whether a source was saved and whether normalization completed.
9. The beekeeper compares facts with the source on `/logs/{id}` and confirms review.

Failure after step 3 retains the original record and ID. Failed attempts remain
visible and can be reprocessed from the saved transcript. No fallback inspection,
inferred score or recommendation is created. Completed sources return the same
inspection on retry. Application startup does not initialize or change the schema.

See [YA-01](ya-01.md) for status/HTTP conventions, retention/access rules, factual
examples, export contracts, tests and operating instructions.
