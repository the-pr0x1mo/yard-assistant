# Life of a voice log

1. The browser records/uploads audio to `/api/voice` (alias `/voice`).
2. Whisper produces text; exact segment text is preserved. Temporary audio is
   deleted after transcription or failure. No database writes occur.
3. Ollama attempts factual extraction once using the existing YA-01 contract.
4. The server returns a signed, ephemeral review with the original transcript.
   Failed extraction produces NULL factual fields for manual entry.
5. The beekeeper selects/creates an identified hive, optionally edits facts and
   explicitly confirms or discards. Transcript editing is unavailable.
6. Confirmation transactionally saves the transcript, actual extraction attempt,
   hive/name and final confirmed inspection. New audio fields stay NULL.
7. Retries return the same persisted inspection. Failed confirmation preserves the
   browser form; discard/navigation/reload loses an unconfirmed review.
8. Dashboards/CSV/JSON use approved, persisted facts. Structured corrections update
   the same inspection ID, preserving original transcript and immutable links.

No cookies, sessions, browser draft storage, autosave or background queue is used.
Application startup only checks the existing v2 schema. See [YA-02](ya-02.md) for
API contracts, retention, tests, manual checks, deployment and rollback.
