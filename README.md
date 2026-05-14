# Yard Assistant

Self-hosted AI voice logger for beehive inspections.

## Overview

Yard Assistant is an early MVP for keeping inspection notes in a small apiary.
It records spoken observations, transcribes them, stores the raw transcript, and
then attempts to extract structured inspection data that can be shown in a local
dashboard.

The project is built for beekeepers who want better field notes without spending
extra time typing while a hive is open.

## Why I built this

Good beekeeping records make it easier to understand colony state over time:
brood, food stores, queen observations, colony strength, signs of swarming, and
follow-up actions. In practice, writing those details down during or after an
inspection can be slow and easy to forget, especially in the field.

Yard Assistant explores a voice-first workflow: speak observations during an
inspection, keep the exact transcript as the source of truth, and let the system
try to turn that transcript into useful structured records.

## Features

- Browser-based voice recording and audio upload
- Local speech-to-text transcription with Whisper
- Local LLM-based extraction through Ollama
- Raw transcript storage as an audit trail
- Best-effort normalized inspection records in SQLite
- Server-rendered dashboard pages for hives, inspections, transcripts, and stats
- CSV, JSON, and SQLite export endpoints

## Architecture

See [docs/architecture.md](docs/architecture.md) for the current system design,
request flow, and component responsibilities.

## Tech stack

- FastAPI
- Jinja2
- SQLite
- Pydantic
- faster-whisper
- Ollama / local Llama model
- Docker Compose

## How it works

1. A beekeeper records an inspection note in the browser.
2. The backend transcribes the audio with Whisper.
3. The raw transcript is stored in SQLite.
4. The transcript is sent to a local LLM for experimental structured extraction.
5. Validated structured data is saved when possible and displayed in the UI.

Raw transcript storage is currently the most reliable and important part of the
MVP. Even when structured extraction is incomplete or wrong, the original spoken
note remains available and attached to the detected hive record.

## Running locally

See [docs/deployment.md](docs/deployment.md) and
[docs/troubleshooting.md](docs/troubleshooting.md).

## Current status

Yard Assistant is an early MVP. It is useful for capturing and reviewing raw
inspection transcripts, but structured extraction is still experimental.

Current limitations:

- Serbian beekeeping terminology is not reliably recognized or normalized yet.
- Hive and colony names should be spoken consistently for best results.
- Structured fields may be incomplete, incorrect, or low confidence.
- There is no review/confirm step before saving normalized inspection data.
- Authentication is expected to be handled by the deployment environment, such
  as tailnet access.
- Automated tests are not yet in place.

## Roadmap

See [docs/roadmap.md](docs/roadmap.md).

## Security notes

This project is intended for self-hosted use. Do not expose it directly to the
public internet without adding appropriate authentication, authorization, TLS,
backups, and operational hardening.

## Screenshots

Screenshots are available in [docs/screenshots](docs/screenshots/).

## Acknowledgements

This is my first public open-source project, developed with help from ChatGPT as a coding and writing assistant.

## License

Yard Assistant is released under the MIT License. See [LICENSE](LICENSE).
