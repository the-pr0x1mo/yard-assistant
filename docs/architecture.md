# Architecture

Yard Assistant is a self-hosted, voice-first beekeeping logbook. It uses a server-side rendered UI for simple dashboard pages and a local AI pipeline for converting audio notes into structured inspection records.

The current lifecycle and schema are documented in [YA-01](ya-01.md).
The diagram below is conceptual; durable source storage occurs **before** Ollama.

## High-Level Architecture

![Yard Assistant architecture](./architecture-diagram.png)

GET requests render dashboard pages server-side using FastAPI, SQLite, and Jinja2.

POST requests upload audio notes to FastAPI. The backend passes audio to Whisper for transcription, sends the transcript to Ollama for structured extraction, validates the result with Pydantic, and stores both raw and structured records in SQLite.

The MVP treats the raw transcript as the source of truth. The raw audit log is
written first, and the normalized inspection insert is best effort. This keeps
the original spoken note available even when structured extraction fails or
produces invalid data.

## Request Flow

For a step-by-step walkthrough of the ingestion flow, see [Life of a Voice Log](life-of-a-voice-log.md).

### Dashboard / Read Flow

```text
Phone / Browser
    |
    | HTTPS via Tailscale
    v
FastAPI App
    |
    | SQL query
    v
SQLite
    |
    | query results
    v
FastAPI App
    |
    | render template
    v
Jinja2 UI
    |
    | rendered HTML response
    v
Phone / Browser
```

### Voice / Write Flow

```text
Phone / Browser
    |
    | audio upload via HTTPS / Tailscale
    v
FastAPI App
    |
    | audio file
    v
Whisper STT
    |
    | transcript text
    v
SQLite: commit source audio + transcript
    |
    v
Ollama / Llama
    |
    | structured JSON
    v
Pydantic Validation
    |
    | validated structured data
    v
SQLite
```
For a step-by-step walkthrough of the ingestion flow, see [Life of a Voice Log](life-of-a-voice-log.md).

## Component Responsibilities

| Component | Responsibility |
|---|---|
| FastAPI | API and server-side rendered backend |
| Jinja2 | HTML template rendering |
| Whisper STT | Audio-to-text transcription |
| Ollama / Llama | Local LLM-based structured extraction |
| Pydantic | Schema validation and data normalization |
| SQLite | Stores raw logs and structured inspection data |
| Tailscale | Secure HTTPS access for browser microphone support |

## Data Reliability Notes

- `hive_logs` preserves source audio, the raw transcript and processing statuses for audit and
  recovery.
- `extraction_attempts` preserves model responses and validated candidates;
  `inspections` stores the committed factual observations with explicit source linkage.
- Structured extraction is experimental, especially for Serbian beekeeping
  terminology, so downstream views should treat normalized fields as editable or
  reviewable data rather than guaranteed facts.
