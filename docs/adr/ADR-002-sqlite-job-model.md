# ADR-002: SQLite And Single-Process Jobs

- Status: accepted
- Date: 2026-08-20

## Decision

Use SQLite with foreign keys, WAL mode and bounded transactions. Pipeline work uses explicit idempotency keys and persisted job states. Redis, PostgreSQL, Kafka and Celery are excluded from the MVP.

## Consequences

The deployment is simple and reproducible on one host. Scaling beyond one active writer requires a later architecture review and a data migration plan.
