# Deployment

This document describes a simple self-hosted deployment for Yard Assistant using Docker Compose.

Yard Assistant is currently intended for trusted local or tailnet environments. It should not be exposed directly to the public internet without authentication, TLS, backups, and operational hardening.

## Requirements

- Linux server or workstation
- Docker
- Docker Compose
- Tailscale, recommended for HTTPS access and browser microphone support
- Optional NVIDIA GPU support for faster local AI workloads

## Environment configuration

Create a local `.env` file from `.env.example`:

```bash
cp .env.example .env
```

Example:

```env
DATABASE_PATH=/data/logbook.dev.sqlite
OLLAMA_BASE_URL=http://ollama:11434
OLLAMA_MODEL=llama3.2:3b
WHISPER_MODEL=base
WHISPER_DEVICE=cpu
WHISPER_COMPUTE=int8
```

The database path is configured through `DATABASE_PATH`.

Recommended local database layout:

```text
data/
  logbook.dev.sqlite
  logbook.field.sqlite
```

Use `logbook.dev.sqlite` for testing and development. Use `logbook.field.sqlite` for real apiary records.

## Starting the application

Build and start the services:

```bash
docker compose up -d --build
```

Check running containers:

```bash
docker compose ps
```

Check logs:

```bash
docker compose logs -f
```

## Health check

From the server:

```bash
curl http://127.0.0.1:8000/health
```

If the health endpoint returns a valid response, the FastAPI backend is running.

## Browser access

For local testing, open:

```text
http://SERVER_IP:8000
```

Browser microphone access usually requires a secure context. Plain HTTP works for localhost, but not reliably for remote devices such as phones.

For phone-based recording, use HTTPS through Tailscale Serve.

## HTTPS with Tailscale Serve

Yard Assistant can be served over HTTPS inside your tailnet:

```bash
sudo tailscale serve --bg --https=443 http://127.0.0.1:8000
```

Check the serve configuration:

```bash
tailscale serve status
```

Then open the Tailscale HTTPS URL from a device in the same tailnet:

```text
https://<device>.<tailnet>.ts.net
```

Do not use:

```text
https://SERVER_IP:8000
```

Port 8000 serves plain HTTP unless you explicitly place it behind an HTTPS reverse proxy.

## Database setup

The following commands assume the `sqlite3` CLI is installed on the host.

If the database file does not exist, initialize it from the schema:

```bash
mkdir -p data
sqlite3 data/logbook.dev.sqlite < assistant-api/app/schema.sql
```

For real field usage:

```bash
sqlite3 data/logbook.field.sqlite < assistant-api/app/schema.sql
```

Then set:

```env
DATABASE_PATH=/data/logbook.field.sqlite
```

Restart the application:

```bash
docker compose up -d
```

## Switching databases

To switch between development and field databases, change `DATABASE_PATH` in `.env`.

Example:

```env
DATABASE_PATH=/data/logbook.dev.sqlite
```

or:

```env
DATABASE_PATH=/data/logbook.field.sqlite
```

Then restart:

```bash
docker compose up -d
```

A rebuild is usually not required when only changing environment variables.

## Backup

SQLite database files should be backed up regularly.

Simple manual backup:

```bash
mkdir -p backups
cp data/logbook.field.sqlite backups/logbook.field.$(date +%Y%m%d-%H%M%S).sqlite
```

Before making schema changes or testing new extraction logic against real data, create a backup.

## Security notes

- Do not commit `.env` files.
- Do not commit real SQLite databases.
- Do not expose the application directly to the public internet without authentication and TLS.
- Prefer Tailscale or another private network for access.
- Treat raw transcripts as potentially sensitive field notes.

## Troubleshooting

Check containers:

```bash
docker compose ps
```

Check logs:

```bash
docker compose logs -f assistant-api
```

Check whether the backend is reachable:

```bash
curl http://127.0.0.1:8000/health
```

Check Tailscale Serve:

```bash
tailscale serve status
```

If microphone access fails, confirm that the browser is using HTTPS and that microphone permission is allowed for the site.
