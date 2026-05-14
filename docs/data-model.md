# Data Model

Yard Assistant uses SQLite as its local storage layer.

The data model follows an audit-first approach:

```text
raw voice/transcript log first
normalized inspection data second
derived dashboard views last
```

The most important rule is that the original transcript should be preserved even if structured extraction fails or produces incomplete data.

For request and processing flows, see [Architecture](architecture.md) and [Life of a Voice Log](life-of-a-voice-log.md).

## Tables and Views

### `hive_logs`

Raw audit trail for voice logs and parsing results.

This table stores the original transcript and related processing payloads. It is the most important persistence layer in the MVP because it preserves what the beekeeper actually said.

Purpose:

- preserve raw transcripts
- keep original inspection observations available
- support debugging of speech-to-text and LLM extraction
- allow future re-processing with better prompts or models

Example responsibility:

```text
voice note → transcript → raw log entry
```

### `hives`

Master table for known hives or colonies.

This table represents the stable hive records used across inspections.

Purpose:

- store hive identity
- provide stable references for inspections
- support dashboards and history views per hive

Example:

```text
Hive 1
Hive 2
Colony Alpha
```

### `inspections`

Independent inspection records.

Each row represents one inspection event or observation session. An inspection may come from a voice log, a manual entry, or future input methods.

Purpose:

- track when an inspection happened
- connect an inspection to a hive
- store inspection-level notes and metadata
- provide history over time

Conceptually:

```text
one hive → many inspections
```

### `inspection_metrics`

Derived or extracted inspection metrics.

This table stores structured values extracted from the transcript or entered later. These values are considered normalized, but in the MVP they should still be treated as best-effort unless reviewed.

Purpose:

- store brood frame count
- store food/reserve estimate
- store queen status fields
- store colony strength indicators
- store swarm risk or readiness metrics
- support dashboard summaries and future analytics

Important:

```text
inspection_metrics are derived from raw observations.
They should not replace the raw transcript.
```

### `v_hive_latest`

Dashboard view for the latest known hive state.

This SQL view is used to display the most recent summarized state of each hive without manually querying and joining the latest inspection data every time.

Purpose:

- simplify dashboard queries
- show one row per hive
- surface latest inspection status
- support the `/hives` overview page

Example dashboard use:

```text
Hive | Last inspection | Strength | Food | Queen status | Action
```

## Data Reliability Layers

Yard Assistant treats stored data in layers:

```text
hive_logs
    most reliable raw audit trail

inspections
    normalized inspection events

inspection_metrics
    best-effort structured extraction

v_hive_latest
    derived dashboard summary
```

The raw transcript is the source of truth. Normalized fields are useful for dashboards, filtering, and future analytics, but they should remain reviewable and correctable.

## Design Notes

- `hive_logs` is append-oriented and should preserve original observations.
- `hives` contains stable hive identity.
- `inspections` represents inspection events.
- `inspection_metrics` contains structured, extracted, or derived values.
- `v_hive_latest` exists to make dashboard rendering simpler.
- Future versions may add review/confirm flows before normalized metrics become trusted records.