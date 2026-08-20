from __future__ import annotations

from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Entity, EntityAlias, Industry, Source
from .schemas import SourceCreate


def load_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def bootstrap_catalog(
    session: Session,
    config_dir: Path,
    *,
    include_demo: bool = True,
) -> None:
    for payload in load_yaml(config_dir / "sources.yaml").get("sources", []):
        if payload.get("is_demo", False) and not include_demo:
            continue
        source_data = SourceCreate.model_validate(payload).model_dump()
        existing = session.get(Source, source_data["id"])
        if existing is None:
            session.add(Source(**source_data))
        else:
            for key, value in source_data.items():
                setattr(existing, key, value)

    for payload in load_yaml(config_dir / "industries.yaml").get("industries", []):
        existing = session.get(Industry, payload["id"])
        values = {
            "id": payload["id"],
            "scheme": payload.get("scheme", "ISIC-derived"),
            "code": str(payload["code"]),
            "name": payload["name"],
            "parent_id": payload.get("parent_id"),
            "keywords": payload.get("keywords", []),
        }
        if existing is None:
            session.add(Industry(**values))
        else:
            for key, value in values.items():
                setattr(existing, key, value)

    session.flush()
    for payload in load_yaml(config_dir / "company_aliases.yaml").get("entities", []):
        if payload["id"].startswith("demo_") and not include_demo:
            continue
        existing = session.get(Entity, payload["id"])
        values = {
            "id": payload["id"],
            "entity_type": payload.get("entity_type", "company"),
            "canonical_name": payload["canonical_name"],
            "country": payload.get("country"),
            "parent_id": payload.get("parent_id"),
            "identifiers_json": payload.get("identifiers", {}),
            "industry_id": payload.get("industry_id"),
        }
        if existing is None:
            existing = Entity(**values)
            session.add(existing)
        else:
            for key, value in values.items():
                setattr(existing, key, value)
        session.flush()
        current_aliases = {
            row.alias
            for row in session.scalars(
                select(EntityAlias).where(EntityAlias.entity_id == existing.id)
            )
        }
        for alias in payload.get("aliases", []):
            if alias not in current_aliases:
                session.add(
                    EntityAlias(
                        entity_id=existing.id,
                        alias=alias,
                        language="zh"
                        if any("\u3400" <= char <= "\u9fff" for char in alias)
                        else "en",
                    )
                )
    session.commit()
