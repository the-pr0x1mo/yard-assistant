# Deployment

For an existing v2 database, follow [YA-02 deployment and rollback](ya-02.md#safe-deployment-and-rollback).
Keep the configured database path and schema; no initialization, migration, reset,
new production database or audio cleanup is part of this upgrade.

`DB_PATH` takes precedence over `DATABASE_PATH`, then `/data/logbook.sqlite`.
Keep existing mounts, models, GPU, network and TLS configuration. The default API
uses one worker; multiple workers require the same strong `REVIEW_SIGNING_KEY`.
Without it restarting the process invalidates open review cards.

For first-time disposable development databases only, use the explicit init/seed
commands in [YA-01 setup](ya-01.md#local-setup-and-tests). Startup only checks v2.
Browser microphone recording needs localhost or the existing HTTPS origin.

[Audio cleanup](ya-02.md#audio-cleanup-operator-action-only) is a separate, explicit
maintenance operation requiring stopped writers and a newly verified full backup.
