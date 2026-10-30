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
- Original transcripts retained only with explicit inspection confirmation
- Strict factual extraction with visible failure states and linked SQLite records
- Temporary audio processing; confirmed transcripts and extraction metadata
- Editable review cards, explicit confirmation and correction of saved inspections
- Server-rendered dashboard pages for hives, inspections, transcripts, and stats
- Approved inspection CSV/JSON, latest-hive CSV and audio-free SQLite snapshots

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
3. Ollama attempts factual extraction; the browser displays an ephemeral review card.
4. The beekeeper selects a hive and reviews or fills structured fields.
5. Explicit confirmation atomically stores the original transcript, extraction
   attempt and approved inspection. Audio is never retained.
6. Saved inspections can be corrected in place while their original transcript
   and stable hive/source links remain unchanged.

Failed extraction still permits manual review when Whisper produced valid text.
Unconfirmed cards are lost on navigation, reload or discard.

## YA-02 review and correction

See [YA-02](docs/ya-02.md) for API changes, existing v2 database compatibility,
verified audio cleanup, tests, browser checklist, deployment and rollback.
The same database path and schema are retained; no migration or initialization
is required for existing v2 databases.

## Initial development setup

See [the extraction and database guide](docs/ya-01.md) for the v2 factual contract,
explicit database initialization, deterministic test-data seed, separate development
reset, tests, deployment and rollback. Startup never initializes, migrates or resets
a database. Legacy synthetic schemas are refused until the operator selects a new
v2 database or performs an explicit backed-up development reset.

## Running locally

See [docs/deployment.md](docs/deployment.md) and
[docs/troubleshooting.md](docs/troubleshooting.md).

## Current status

Yard Assistant is an early MVP. It is useful for capturing and reviewing raw
inspection transcripts, but structured extraction is still experimental.

Current limitations:

- Serbian beekeeping terminology is not reliably recognized or normalized yet.
- Hive and colony names should be spoken consistently for best results.
- Structured fields may be incomplete or incorrect; review them before confirmation.
- Open review cards are intentionally temporary; confirm before leaving the page.
- Authentication is expected to be handled by the deployment environment, such
  as tailnet access.
- Deterministic tests mock Whisper/Ollama; live-model accuracy still needs manual checks.

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
