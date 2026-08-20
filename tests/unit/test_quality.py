import json
from pathlib import Path

import pytest
from news_claws.database import get_engine, session_factory
from news_claws.models import Base, EventCluster
from news_claws.quality import (
    QualityLabel,
    load_database_predictions,
    load_quality_labels,
    quality_gate_failures,
    score_quality,
)


def test_quality_scores_and_gate_are_explicit() -> None:
    labels = [
        QualityLabel("event_1", True, ("industry_a",), ("company_a",)),
        QualityLabel("event_2", False, ("industry_b",), ("company_b",)),
    ]
    predictions = {
        "event_1": {
            "industry_ids": ["industry_a"],
            "company_ids": ["company_a"],
        },
        "event_2": {
            "industry_ids": ["industry_wrong"],
            "company_ids": ["company_b", "company_wrong"],
        },
    }

    scores = score_quality(labels, predictions)

    assert scores == {
        "event_count": 2,
        "cluster_accuracy": 0.5,
        "industry_top3_precision": 0.5,
        "company_top5_precision": 0.75,
    }
    failures = quality_gate_failures(scores)
    assert any("event_count" in failure for failure in failures)
    assert any("cluster_accuracy" in failure for failure in failures)


def test_quality_label_file_rejects_duplicate_events(tmp_path) -> None:
    label = {
        "event_id": "event_1",
        "cluster_correct": True,
        "expected_industry_ids": [],
        "expected_company_ids": [],
    }
    path = tmp_path / "labels.jsonl"
    path.write_text(
        json.dumps(label) + "\n" + json.dumps(label) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate event_id"):
        load_quality_labels(path)


def test_database_predictions_require_existing_non_demo_events(tmp_path: Path) -> None:
    database_url = f"sqlite:///{(tmp_path / 'quality.db').as_posix()}"
    Base.metadata.create_all(get_engine(database_url))

    with session_factory(database_url)() as session:
        session.add_all(
            [
                EventCluster(id="event_live", title="Live event", is_demo=False),
                EventCluster(id="event_demo", title="Demo event", is_demo=True),
            ]
        )
        session.commit()

        assert load_database_predictions(session, ["event_live"]) == {
            "event_live": {"industry_ids": [], "company_ids": []}
        }
        with pytest.raises(ValueError, match="do not exist"):
            load_database_predictions(session, ["event_missing"])
        with pytest.raises(ValueError, match="Demo events are not permitted"):
            load_database_predictions(session, ["event_demo"])
