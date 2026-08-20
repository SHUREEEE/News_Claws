from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Entity, EntityAlias


@dataclass(frozen=True)
class CompanyRecord:
    stable_id: str
    canonical_name: str
    country: str
    market: str
    ticker: str
    aliases: tuple[str, ...] = ()
    industry_id: str | None = None
    identifiers: dict[str, str] | None = None


def _language(value: str) -> str:
    return "zh" if any("\u3400" <= char <= "\u9fff" for char in value) else "en"


def upsert_company_records(session: Session, records: list[CompanyRecord]) -> int:
    if not records:
        raise ValueError("Company catalog did not contain any valid records")
    if len({record.stable_id for record in records}) != len(records):
        raise ValueError("Company catalog contains duplicate stable IDs")

    entity_ids = {record.stable_id for record in records}
    entities = {
        entity.id: entity
        for entity in session.scalars(select(Entity).where(Entity.id.in_(entity_ids)))
    }
    aliases_by_entity: dict[str, set[tuple[str, str]]] = {}
    for alias in session.scalars(select(EntityAlias).where(EntityAlias.entity_id.in_(entity_ids))):
        aliases_by_entity.setdefault(alias.entity_id, set()).add((alias.alias, alias.alias_type))

    processed = 0
    for record in records:
        name = record.canonical_name.strip()
        ticker = record.ticker.strip().upper()
        if not name or not ticker:
            continue
        identifiers = {
            "ticker": ticker,
            "market": record.market.strip().upper(),
            **(record.identifiers or {}),
        }
        entity = entities.get(record.stable_id)
        if entity is None:
            entity = Entity(
                id=record.stable_id,
                entity_type="company",
                canonical_name=name,
                country=record.country,
                identifiers_json=identifiers,
                industry_id=record.industry_id,
            )
            session.add(entity)
            entities[record.stable_id] = entity
        else:
            entity.canonical_name = name
            entity.country = record.country
            entity.identifiers_json = identifiers
            entity.industry_id = record.industry_id

        known_aliases = aliases_by_entity.setdefault(record.stable_id, set())
        alias_values = [(name, "name"), (ticker, "ticker")]
        alias_values.extend((alias.strip(), "name") for alias in record.aliases if alias.strip())
        for alias_value, alias_type in alias_values:
            key = (alias_value, alias_type)
            if key in known_aliases:
                continue
            session.add(
                EntityAlias(
                    entity_id=record.stable_id,
                    alias=alias_value,
                    language=_language(alias_value),
                    alias_type=alias_type,
                )
            )
            known_aliases.add(key)
        processed += 1
    session.commit()
    return processed


def _sec_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = payload.values() if all(str(key).isdigit() for key in payload) else []
    validated: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if not {"cik_str", "ticker", "title"}.issubset(row):
            continue
        validated.append(row)
    return validated


def upsert_sec_company_catalog(
    session: Session,
    payload: dict[str, Any],
    *,
    limit: int | None = None,
) -> int:
    rows = _sec_rows(payload)
    if limit is not None:
        rows = rows[:limit]
    if not rows:
        raise ValueError("SEC company catalog did not contain valid company rows")

    records: list[CompanyRecord] = []
    for row in rows:
        cik = int(row["cik_str"])
        ticker = str(row["ticker"]).strip().upper()
        title = str(row["title"]).strip()
        if not title or not ticker:
            continue
        records.append(
            CompanyRecord(
                stable_id=f"sec_cik_{cik:010d}",
                canonical_name=title,
                country="US",
                market="US",
                ticker=ticker,
                identifiers={"cik": f"{cik:010d}"},
            )
        )
    return upsert_company_records(session, records)
