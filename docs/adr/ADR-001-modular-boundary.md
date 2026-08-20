# ADR-001: Modular Boundary

- Status: accepted
- Date: 2026-08-20

## Decision

TrendRadar and trendradar-mcp remain replaceable upstream services. The self-developed `analysis-api` owns normalized articles, versions, event clusters, claims, evidence, verification, impacts, reports and feedback. It consumes upstream data only through an explicit adapter contract and never reads private TrendRadar tables.

## Consequences

The local MVP includes a fixture/RSS adapter so it runs before TrendRadar is configured. GPL/AGPL services stay out of the application process and communicate over a stable network boundary.
