# ADR-003: Conservative Evidence-First Analysis

- Status: accepted
- Date: 2026-08-20

## Decision

Verification is derived from primary-material applicability, evidence quality, independence groups and conflicts. Multiple copies of one release remain one information chain. Official material proves the authority made or published the cited statement; it does not make every embedded claim true.

LLM adapters are optional and must return strict JSON. Server code validates every referenced `evidence_id` against the supplied whitelist. External output uses confidence levels and explanatory factors, not uncalibrated truth probabilities.
