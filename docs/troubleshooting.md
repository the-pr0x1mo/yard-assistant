# Troubleshooting

This document lists common Yard Assistant issues and quick checks.

## Check running services

```bash
docker compose ps
```

Check logs:

```bash
docker compose logs -f
```

For only the API service:

```bash
docker compose logs -f assistant-api
```

## Backend health check

From the server:

```bash
curl http://127.0.0.1:8000/health
```

If this fails, the FastAPI backend is not reachable.

## Template or UI changes are not visible

Rebuild and restart the containers:

```bash
docker compose up -d --build
```

If changes still do not appear:

```bash
docker compose down
docker compose up -d --build
```

Then hard refresh the browser:

```text
Ctrl + Shift + R
```

On mobile Safari, close the tab completely and open it again.

## Microphone access failed

Browser microphone access usually requires HTTPS, except for `localhost`.

Use Tailscale Serve or another HTTPS reverse proxy for phone-based recording.

Check Tailscale Serve:

```bash
tailscale serve status
```

Example Tailscale Serve setup:

```bash
sudo tailscale serve --bg --https=443 http://127.0.0.1:8000
```

Then open the HTTPS MagicDNS URL:

```text
https://<device>.<tailnet>.ts.net
```

Do not use:

```text
https://SERVER_IP:8000
```

Port `8000` serves plain HTTP unless placed behind HTTPS.

Also check browser permissions:

- microphone permission is allowed
- the page is not opened in a restricted/private context
- the URL is using HTTPS

## HTTPS opens the wrong service

If another service is running on port `80`, opening the server hostname without a port may show that service instead of Yard Assistant.

Check listening ports:

```bash
sudo ss -tulpn | grep -E ':80|:443|:8000'
```

Check containers and exposed ports:

```bash
docker ps --format "table {{.Names}}\t{{.Ports}}\t{{.Status}}"
```

Common pattern:

```text
http://SERVER:80       -> reverse proxy or another local service
http://SERVER:8000     -> Yard Assistant plain HTTP
https://TAILSCALE_URL  -> Yard Assistant through Tailscale Serve
```

## Upload failed

Check API logs while retrying the upload:

```bash
docker compose logs -f assistant-api
```

Check whether the API is reachable:

```bash
curl http://127.0.0.1:8000/health
```

If using a reverse proxy or Tailscale Serve, confirm that requests reach the FastAPI backend.

Common causes:

- backend container is down
- wrong URL or route
- microphone permission failed
- HTTPS/proxy routing issue
- audio file too large
- transcription or LLM processing error

## Wrong database is being used

Check the configured database path:

```bash
grep DATABASE_PATH .env
```

Expected examples:

```env
DATABASE_PATH=/data/logbook.dev.sqlite
```

or:

```env
DATABASE_PATH=/data/logbook.field.sqlite
```

Restart after changing `.env`:

```bash
docker compose up -d
```

A rebuild is usually not required when only changing environment variables.

Check that the host `data/` directory is mounted into the container as `/data`.

## Database file does not exist

Initialize a database from the schema:

```bash
mkdir -p data
sqlite3 data/logbook.dev.sqlite < assistant-api/app/schema.sql
```

For field usage:

```bash
sqlite3 data/logbook.field.sqlite < assistant-api/app/schema.sql
```

Then set `DATABASE_PATH` in `.env`.

## Ollama connection issues

Check that the Ollama container is running:

```bash
docker compose ps
```

Check logs:

```bash
docker compose logs -f ollama
```

Check the configured URL:

```bash
grep OLLAMA_BASE_URL .env
```

Inside Docker Compose, the expected value is usually:

```env
OLLAMA_BASE_URL=http://ollama:11434
```

If the model is missing, pull it:

```bash
docker compose exec ollama ollama pull llama3.2:3b
```

## Whisper or transcription is slow

Transcription speed depends on:

- CPU performance
- selected Whisper model size
- audio length
- whether GPU acceleration is available

For slower machines, use a smaller model in `.env`:

```env
WHISPER_MODEL=base
WHISPER_DEVICE=cpu
WHISPER_COMPUTE=int8
```

## Check recent logs and data

Useful pages:

```text
/transcripts
/inspections
/hives
/stats
```

If the structured inspection is missing but the transcript exists, the raw logging path worked and structured extraction likely failed or produced invalid data.

## Reset Tailscale Serve

If HTTPS routing becomes confusing:

```bash
sudo tailscale serve reset
```

Then configure Yard Assistant again:

```bash
sudo tailscale serve --bg --https=443 http://127.0.0.1:8000
```

Check:

```bash
tailscale serve status
```