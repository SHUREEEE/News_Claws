# Real-Data Clustering Audit

Date: 2026-08-20

Evidence class: verified fact unless explicitly marked otherwise.

## Scope

- Replayed every enabled non-demo source into fresh, isolated SQLite databases.
- Limited each source to five current entries.
- Preserved the pre-repair `data/analysis.db`; no existing database was overwritten or deleted.
- Audited every event containing more than one article, not only the originally reported pair.

## Checker Return 1

The pre-repair event `evt_2dcb5faab503478897a0` contained two unrelated articles:

- `Scottish Secretary comments on latest Labour Market Statistics`
- `CMA publishes latest monitoring update on road fuel market`

Their title score was 0.214 and the previous live threshold was 0.20.

Repair:

- Live threshold: 0.72.
- Demo threshold: 0.20, isolated to demo events.
- Candidate state: active and unlocked only.
- Candidate time window: incoming publication time plus or minus seven days.

Focused result: 13 tests passed.

## Checker Return 2

The first fresh replay passed all 52 sources and ingested 260 articles, but the all-cluster audit found:

- `DfE Update 19 August 2026` grouped with `DfE Update 5 August 2026`.
- EBA alerts for 3, 5 and 6 August grouped together.

The tokenizer ignored standalone one-digit numbers. The repair retains standalone numeric tokens.

Focused result after removing a duplicate test definition: 15 tests passed and Ruff passed.

## Final Fresh Replay

| Measure | Result |
|---|---:|
| Configured enabled live sources | 52 |
| Initial successful sources | 50 |
| Sources successful after one bounded retry | 52 |
| Articles | 260 |
| Events | 254 |
| Multi-article events | 5 |
| Database integrity | ok |

All five multi-article events used identical titles across at least two configured sources:

- Keep Britain Working review update: June 2026
- PM orders crackdown on illegal-waste criminal gangs
- Sovereign AI invests in a UK AI-chip startup
- Joint Statement on Asbestos in Consumer Products
- Free bus travel for disabled people

The known ONS/CMA pair, EBA dated alerts and DfE dated updates each had distinct event IDs.

## Boundary

Decision: the fresh replay validates the deterministic clustering repair and live-source path. It does not establish semantic recall, industry/company accuracy, or the release quality thresholds. Those remain blocked on a human-reviewed benchmark of at least 200 real events.
