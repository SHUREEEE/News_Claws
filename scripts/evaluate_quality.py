from __future__ import annotations

import argparse
import json
from pathlib import Path

from news_claws.database import session_factory
from news_claws.quality import (
    load_database_predictions,
    load_quality_labels,
    quality_gate_failures,
    score_quality,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate News Claws against a human-labeled JSONL benchmark"
    )
    parser.add_argument("labels", type=Path)
    parser.add_argument("--minimum-events", type=int, default=200)
    parser.add_argument("--cluster-threshold", type=float, default=0.90)
    parser.add_argument("--industry-threshold", type=float, default=0.80)
    parser.add_argument("--company-threshold", type=float, default=0.80)
    args = parser.parse_args()
    if args.minimum_events < 1:
        raise SystemExit("--minimum-events must be at least 1")

    try:
        labels = load_quality_labels(args.labels)
    except (OSError, ValueError) as exc:
        raise SystemExit(f"Quality benchmark is invalid: {exc}") from exc
    with session_factory()() as session:
        predictions = load_database_predictions(
            session,
            [label.event_id for label in labels],
        )
    scores = score_quality(labels, predictions)
    failures = quality_gate_failures(
        scores,
        minimum_events=args.minimum_events,
        cluster_threshold=args.cluster_threshold,
        industry_threshold=args.industry_threshold,
        company_threshold=args.company_threshold,
    )
    print(json.dumps({**scores, "passed": not failures, "failures": failures}, indent=2))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
