# ADR-004: Retain Reposts Without Global Content Uniqueness

- Status: accepted
- Date: 2026-08-20

## Context

The technical baseline suggested a unique index on `article.content_hash`, while the product contract requires all repost records to remain visible and requires article count to differ from independent source-chain count.

## Decision

Article identity is unique by `(source_id, canonical_url)`. `content_hash` is indexed but not globally unique. Exact-content copies create syndication links and share an independence group.

## Consequences

The system can display ten reposted articles while correctly counting one information chain. This is a deliberate clarification of the baseline rather than a scope expansion.
