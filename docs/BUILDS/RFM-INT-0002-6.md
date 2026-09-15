# RFM-INT-0002.6 — Durable Transformation Sessions

## Why this build exists

Founder testing exposed a critical infrastructure failure: transformation sessions were stored in SQLite on the Render web-service filesystem. That filesystem is ephemeral, so a deploy/restart can erase the database file and make an active session URL return `Lab session not found`.

This is not acceptable for RUINFORM. Project state is part of the intelligence system and must survive deploys, restarts, and model upgrades.

## Decision

- PostgreSQL becomes the production session store whenever `DATABASE_URL` or `RUINFORM_DATABASE_URL` is configured.
- SQLite remains available only for local development/tests or hosts with a genuinely persistent disk.
- Existing code that constructs `SqliteRunStore()` is kept backward compatible: with a database URL configured, the constructor transparently routes to `PostgresRunStore`.
- The Postgres store keeps the same `save/get` contract and persists the complete serialized `TransformationSession`.

## Production setup

A Render Postgres database named `ruinform-intelligence-db` was created in Frankfurt for the live lab. The web service must be given the database's internal connection URL as `DATABASE_URL`.

The current free Render Postgres plan is suitable for founder testing but has a time-limited lifecycle. Before external users or durable production data, move to a non-expiring production database plan and add backups/retention policy.

## Regression protection

Tests verify that:

- local/dev without a database URL still uses SQLite;
- existing `SqliteRunStore()` callers automatically use Postgres when a database URL is configured;
- the explicit run-store factory also prefers Postgres.

## Failure added to the library

**F-011 — Ephemeral session loss**

Symptom: a previously valid `/lab/{session_id}` returns `Lab session not found` after a deploy or restart.

Root cause: authoritative project state stored only on an ephemeral application filesystem.

Permanent rule: authoritative transformation state must use durable storage in deployed environments.

## Next validation

1. connect the Render web service to `ruinform-intelligence-db` via `DATABASE_URL`;
2. create a new lab session;
3. confirm the session row exists in Postgres;
4. deploy/restart the web service;
5. confirm the same session remains readable;
6. continue Concept Mode through Future Discovery.
