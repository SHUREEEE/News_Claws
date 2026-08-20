from pathlib import Path

from news_claws.company_registry import upsert_company_records, upsert_sec_company_catalog
from news_claws.database import get_engine, session_factory
from news_claws.models import Base, Entity, EntityAlias
from sqlalchemy import func, select

from scripts.sync_exchange_companies import load_exchange_csv


def test_sec_company_catalog_is_idempotent_and_traceable(tmp_path: Path) -> None:
    database_url = f"sqlite:///{(tmp_path / 'companies.db').as_posix()}"
    Base.metadata.create_all(get_engine(database_url))
    payload = {
        "0": {"cik_str": 320193, "ticker": "TEST", "title": "Test Devices Inc."},
        "1": {"cik_str": 789019, "ticker": "CLOUD", "title": "Cloud Systems Corp."},
    }
    with session_factory(database_url)() as session:
        assert upsert_sec_company_catalog(session, payload) == 2
        assert upsert_sec_company_catalog(session, payload) == 2
        assert session.scalar(select(func.count()).select_from(Entity)) == 2
        assert session.scalar(select(func.count()).select_from(EntityAlias)) == 4
        company = session.get(Entity, "sec_cik_0000320193")
        assert company is not None
        assert company.identifiers_json["ticker"] == "TEST"
        aliases = {
            (alias.alias, alias.alias_type)
            for alias in session.scalars(
                select(EntityAlias).where(EntityAlias.entity_id == company.id)
            )
        }
        assert aliases == {("Test Devices Inc.", "name"), ("TEST", "ticker")}


def test_exchange_csv_supports_a_share_and_h_share_aliases(tmp_path: Path) -> None:
    catalog = tmp_path / "hkex.csv"
    catalog.write_text(
        "Stock Code,Company Name,Short Name\n"
        "00700,Tencent Holdings Limited,腾讯控股\n"
        "09988,Alibaba Group Holding Limited,阿里巴巴-SW\n",
        encoding="utf-8",
    )
    records = load_exchange_csv(
        catalog,
        market="HKEX",
        country="HK",
        ticker_column="Stock Code",
        name_column="Company Name",
        alias_columns=["Short Name"],
        encoding="utf-8",
    )
    database_url = f"sqlite:///{(tmp_path / 'exchange.db').as_posix()}"
    Base.metadata.create_all(get_engine(database_url))
    with session_factory(database_url)() as session:
        assert upsert_company_records(session, records) == 2
        assert upsert_company_records(session, records) == 2
        company = session.get(Entity, "exchange_hkex_00700")
        assert company is not None
        assert company.country == "HK"
        assert company.identifiers_json == {"ticker": "00700", "market": "HKEX"}
        aliases = {
            (alias.alias, alias.alias_type, alias.language)
            for alias in session.scalars(
                select(EntityAlias).where(EntityAlias.entity_id == company.id)
            )
        }
        assert aliases == {
            ("Tencent Holdings Limited", "name", "en"),
            ("00700", "ticker", "en"),
            ("腾讯控股", "name", "zh"),
        }
