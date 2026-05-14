# Life of a Voice Log

This document describes what happens when a beekeeper records and submits a voice inspection note in Yard Assistant.

The goal of this flow is to preserve the original spoken observation first, then attempt to extract structured inspection data from it.

## High-Level Flow

```text
Browser recording
    ↓
Audio upload
    ↓
FastAPI backend
    ↓
Whisper transcription
    ↓
Raw transcript
    ↓
Ollama / local LLM extraction
    ↓
Structured JSON
    ↓
Pydantic validation
    ↓
SQLite storage
    ↓
Dashboard / transcripts / inspections UI
```

## 1. Recording in the Browser

The user opens Yard Assistant from a phone or browser and records an inspection note.

The browser uses the built-in microphone API to capture audio.

For microphone access to work reliably on phones and remote devices, the application should be opened through a secure HTTPS origin, such as Tailscale Serve.

Example:

```text
https://<device>.<tailnet>.ts.net
```

Plain HTTP may work on `localhost`, but browsers usually block microphone access on insecure remote origins.

## 2. Sending the Audio to the Backend

After recording, the browser sends the audio file to the backend.

The current voice endpoint is:

```text
POST /api/voice
```

The upload is sent as form data with an audio file attached.

Conceptually:

```text
Browser
  POST /api/voice
  file=recording.webm
```

The backend returns a response after the audio has been processed.

The UI does not need to render the full JSON response for normal field use. A simple success or failure status is enough because the resulting data can be reviewed later in the transcripts or inspections pages.

## 3. FastAPI Receives the Request

FastAPI acts as the main application layer.

It receives the uploaded audio file and coordinates the processing pipeline:

```text
FastAPI
    ├─ accepts upload
    ├─ sends audio to transcription
    ├─ stores raw transcript
    ├─ calls structured extraction
    ├─ validates parsed output
    └─ writes data to SQLite
```

FastAPI does not perform speech recognition or LLM extraction by itself. It orchestrates the flow between the application components.

## 4. Whisper Transcribes the Audio

The uploaded audio is passed to Whisper / faster-whisper.

Whisper converts the audio signal into text.

```text
audio file
    ↓
Whisper STT
    ↓
transcript text
```

Example transcript:

```text
Hive 1, queen seen, four frames of brood, enough food, calm colony.
```

The transcript is important because it preserves what the beekeeper actually said, even if later structured extraction is incomplete or wrong.

## 5. Raw Transcript Is Stored

The raw transcript is stored as an audit record.

This is one of the most important design decisions in the MVP.

The raw transcript is treated as the source of truth because speech recognition and LLM extraction are not guaranteed to be perfect.

Even if the structured output fails, the user can still review the original text later.

Example:

```text
Raw transcript:
"Hive 1, queen seen, four frames of brood, enough food."
```

Stored in:

```text
hive_logs
```

The raw log may also include metadata such as the parsed payload, detected hive, confidence, or processing result depending on the current implementation.

## 6. Transcript Is Sent to the Local LLM

After transcription, the transcript text is sent to a local LLM through Ollama.

The LLM attempts to extract structured inspection information from the raw text.

```text
transcript text
    ↓
Ollama / Llama
    ↓
structured JSON
```

Example input:

```text
Hive 1, queen seen, four frames of brood, enough food, calm colony.
```

Example structured output:

```json
{
  "hive": {
    "name": "Hive 1"
  },
  "inspection": {
    "queen_seen": true,
    "notes": "Queen seen. Four frames of brood. Enough food. Colony calm."
  },
  "metrics": {
    "brood_frames": 4,
    "reserves_estimate": "enough",
    "behavior": "calm"
  }
}
```

This structured extraction is currently best-effort and experimental, especially for Serbian beekeeping terminology.

## 7. Pydantic Validates the Structured Data

The LLM output is not trusted blindly.

Before structured data is written to normalized database tables, it is passed through Pydantic models.

Pydantic defines the expected shape of the data:

```text
field names
data types
optional fields
allowed values
defaults
```

It acts as a validation boundary between the AI/parsing layer and the database.

```text
LLM JSON
    ↓
Pydantic validation
    ↓
validated Python object
```

If the data is valid, it can be used for normalized inserts.

If it is invalid or incomplete, the raw transcript is still preserved, and the structured insert may be skipped or partially applied depending on the implementation.

## 8. Data Is Written to SQLite

Yard Assistant stores data in SQLite.

The MVP follows an audit-first approach:

```text
raw transcript first
normalized records best effort
```

Typical storage responsibilities:

```text
hive_logs
    raw transcript and parsing payload

hives
    known hive records

inspections
    inspection-level records

inspection_metrics
    extracted metrics and observations
```

The exact schema may evolve, but the principle stays the same:

```text
Never lose the original spoken note.
Only write structured data when it passes validation.
```

## 9. UI Pages Read the Data

The UI is server-side rendered.

When the user opens pages such as:

```text
/transcripts
/inspections
/hives
/stats
```

FastAPI reads from SQLite, renders Jinja2 templates, and sends complete HTML back to the browser.

```text
Browser GET request
    ↓
FastAPI
    ↓
SQLite query
    ↓
Jinja2 template rendering
    ↓
HTML response
    ↓
Browser
```

The browser does not need to run a full frontend application to display the dashboard.

## 10. What the User Sees

For field usage, the most important feedback is simple:

```text
Recording...
Processing recording...
Uploading...
Saved successfully.
Upload failed.
```

The full raw transcript and any structured data can be reviewed later in:

```text
/transcripts
/inspections
```

This keeps the recording workflow fast and avoids cluttering the field UI with large JSON responses.

## Reliability Model

Yard Assistant currently treats data reliability in layers:

```text
Most reliable:
    raw transcript

Best effort:
    structured LLM extraction

Validated:
    Pydantic-approved structured fields

Displayed:
    dashboard and inspection views
```

This means the MVP remains useful even when structured extraction is imperfect.

The raw transcript can still be reviewed manually and used to improve prompts, vocabulary, and extraction rules over time.

## Current Limitations

- Speech recognition may misrecognize Serbian beekeeping terms.
- Hive names should be spoken consistently.
- Structured extraction may miss or misclassify fields.
- Queen presence may be inferred from brood signs but should not be treated as the same as directly seeing the queen.
- There is not yet a full review/confirm step before saving normalized inspection data.
- Long audio processing may benefit from background jobs in the future.

## Future Improvements

Possible improvements to this flow include:

- review and confirm screen before normalized insert
- standardized Serbian/English beekeeping vocabulary
- confidence scoring for extracted fields
- better hive name aliases
- background job queue for longer processing
- offline-friendly recording and retry behavior
- improved field mode UI
- editable structured inspection records