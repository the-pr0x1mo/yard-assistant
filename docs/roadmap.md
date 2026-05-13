# Roadmap

Yard Assistant is an early MVP. The near-term goal is to make raw voice logging
dependable, then improve the quality and reviewability of structured extraction.

## Next

- Add a review/confirm step before saving normalized inspection data.
- Improve prompt evaluation for Serbian and English beekeeping terminology.
- Build a standard Serbian/English vocabulary for common inspection terms:
  brood, capped brood, open brood, queen, eggs, food frames, pollen, queen cells,
  colony strength, reserves, swarming signs, treatments, and actions.
- Improve handling of Serbian speech-to-text errors, especially cases where
  "kosnica" is misrecognized.
- Define better hive and colony naming conventions for voice input, such as
  stable IDs, spoken aliases, and guidance for avoiding ambiguous names.
- Improve structured extraction from raw transcripts while preserving the raw
  transcript as the source of truth.
- Add sample anonymized transcripts and examples of expected extraction output.

## Model and Extraction

- Compare smaller local models for latency, resource use, and extraction quality.
- Add repeatable prompt/model evaluation cases for Serbian and English notes.
- Track low-confidence extraction results and make them easier to review.
- Separate facts explicitly stated in the transcript from inferred values.
- Improve queen-status logic, for example distinguishing "queen seen" from
  indirect signs such as eggs or young brood.

## Field and Mobile UX

- Improve the mobile recording flow for use during inspections.
- Make transcript review fast on small screens.
- Add clearer feedback while audio is uploading, transcribing, and processing.
- Consider offline-friendly capture or retry behavior for poor connectivity.

## Data and Analytics

- Backup/restore workflow for SQLite.
- Charts for hive strength, food score, and swarm risk.
- Better hive state tracking across inspections.
- Trend views for colony development, food reserves, and follow-up actions.
- Export improvements beyond the current MVP endpoints where needed.

## Infrastructure

- Background job queue for longer audio processing.
- Optional GPU profile for faster transcription.
- Authentication/authorization plan for deployments outside trusted networks.
- Automated tests for parsing, validation, persistence, and exports.

## Documentation TODOs

- Add screenshots to the README or docs when the UI stabilizes.
- Add a sample anonymized transcript.
- Document recommended voice naming conventions for hives/colonies.
- Document known Serbian terminology limitations and accepted vocabulary.
- Add references for beekeeping record-keeping practices and inspection impact
  where claims need external support. TODO: collect credible sources before
  expanding this section.
