from pathlib import Path

from news_claws.database import get_engine, session_factory
from news_claws.models import Base, EventCluster, Source
from news_claws.services import ingest_article
from sqlalchemy import func, select


def _source(source_id: str, *, is_demo: bool = False) -> Source:
    return Source(
        id=source_id,
        name=source_id,
        owner="Test publisher",
        region="UK",
        language="en",
        source_type="government",
        tier="T1",
        official=True,
        method="rss",
        entry_url=f"https://{source_id}.example.test/news",
        is_demo=is_demo,
    )


def _payload(slug: str, title: str) -> dict[str, str]:
    return {
        "url": f"https://news.example.test/{slug}",
        "title": title,
        "published_at": "2026-08-20T08:00:00Z",
        "language": "en",
    }


def test_unrelated_official_news_titles_do_not_cluster(tmp_path: Path) -> None:
    database_url = f"sqlite:///{(tmp_path / 'unrelated.db').as_posix()}"
    Base.metadata.create_all(get_engine(database_url))
    with session_factory(database_url)() as session:
        cma = _source("uk_cma")
        ons = _source("uk_ons")
        session.add_all([cma, ons])
        session.flush()

        _article, first_event, _created = ingest_article(
            session,
            cma,
            _payload("fuel-market", "CMA publishes latest monitoring update on road fuel market"),
        )
        _article, second_event, _created = ingest_article(
            session,
            ons,
            _payload(
                "labour-statistics",
                "Scottish Secretary comments on latest Labour Market Statistics",
            ),
        )

        assert first_event.id != second_event.id
        assert session.scalar(select(func.count()).select_from(EventCluster)) == 2


def test_near_duplicate_cross_publisher_titles_still_cluster(tmp_path: Path) -> None:
    database_url = f"sqlite:///{(tmp_path / 'near-duplicate.db').as_posix()}"
    Base.metadata.create_all(get_engine(database_url))
    with session_factory(database_url)() as session:
        government = _source("uk_government")
        agency = _source("uk_environment_agency")
        session.add_all([government, agency])
        session.flush()

        _article, first_event, _created = ingest_article(
            session,
            government,
            _payload(
                "waste-crackdown-government",
                "Prime Minister orders crackdown on the criminal gangs profiting from illegal "
                "waste and blighting communities",
            ),
        )
        _article, second_event, _created = ingest_article(
            session,
            agency,
            _payload(
                "waste-crackdown-agency",
                "PM orders crackdown on the criminal gangs profiting from illegal waste and "
                "blighting communities",
            ),
        )

        assert first_event.id == second_event.id
        assert session.scalar(select(func.count()).select_from(EventCluster)) == 1


def test_repeated_release_template_with_different_entity_does_not_cluster(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{(tmp_path / 'template.db').as_posix()}"
    Base.metadata.create_all(get_engine(database_url))
    with session_factory(database_url)() as session:
        source = _source("us_federal_reserve")
        session.add(source)
        session.flush()

        _article, first_event, _created = ingest_article(
            session,
            source,
            _payload(
                "approval-coastal-bend",
                "Federal Reserve Board announces approval of the application by Coastal Bend "
                "Bancshares, Inc.",
            ),
        )
        _article, second_event, _created = ingest_article(
            session,
            source,
            _payload(
                "approval-fs-bancorp",
                "Federal Reserve Board announces approval of the application by FS Bancorp, Inc.",
            ),
        )

        assert first_event.id != second_event.id


def test_dated_news_alerts_with_single_digit_days_do_not_cluster(tmp_path: Path) -> None:
    database_url = f"sqlite:///{(tmp_path / 'dated-alerts.db').as_posix()}"
    Base.metadata.create_all(get_engine(database_url))
    with session_factory(database_url)() as session:
        source = _source("eu_eba_news")
        session.add(source)
        session.flush()

        _article, first_event, _created = ingest_article(
            session,
            source,
            _payload("alert-6", "EBA E-mail alert 6 August, 2026"),
        )
        _article, second_event, _created = ingest_article(
            session,
            source,
            _payload("alert-5", "EBA E-mail alert 5 August, 2026"),
        )

        assert first_event.id != second_event.id


def test_live_and_demo_articles_never_share_a_cluster(tmp_path: Path) -> None:
    database_url = f"sqlite:///{(tmp_path / 'data-domain.db').as_posix()}"
    Base.metadata.create_all(get_engine(database_url))
    with session_factory(database_url)() as session:
        demo_source = _source("demo_official", is_demo=True)
        live_source = _source("live_official")
        session.add_all([demo_source, live_source])
        session.flush()

        payload = _payload("shared-headline-demo", "Central bank announces policy decision")
        _article, demo_event, _created = ingest_article(session, demo_source, payload)
        payload = _payload("shared-headline-live", "Central bank announces policy decision")
        _article, live_event, _created = ingest_article(session, live_source, payload)

        assert demo_event.id != live_event.id
        assert demo_event.is_demo is True
        assert live_event.is_demo is False
