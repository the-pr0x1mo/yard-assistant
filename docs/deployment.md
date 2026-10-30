# Deployment

The current database initialization, safe manual deployment and rollback procedure
is maintained in [YA-01 operating guide](ya-01.md#manual-deployment-and-rollback).
Use that procedure before starting the API: v2 requires explicit initialization;
startup refuses missing or incompatible schemas without modifying them.

`DB_PATH` is the primary setting. `DATABASE_PATH` remains an accepted alias only
when `DB_PATH` is absent. Example paths are inside the existing `/data` mount;
no storage, GPU, networking or Tailscale configuration change is required.
Do not change Whisper/Ollama model settings as part of this upgrade.

For local development and synthetic fixtures see
[local setup, tests and explicit reset](ya-01.md#local-setup-and-tests).
Keep reset separate from application startup and stop the API before resetting.

Browser recording requires a secure origin (localhost or the existing HTTPS
access). The existing Tailscale Serve configuration is outside this task.
