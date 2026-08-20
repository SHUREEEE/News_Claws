from __future__ import annotations

import argparse
import asyncio

from news_claws.config import get_settings
from news_claws.database import session_factory
from news_claws.models import Source
from news_claws.services import test_source
from sqlalchemy import select


async def run(source_id: str) -> bool:
    with session_factory()() as session:
        source = session.scalar(select(Source).where(Source.id == source_id))
        if source is None:
            raise SystemExit(f"Source not found: {source_id}")
        try:
            result = await test_source(session, source, get_settings())
        except Exception as exc:
            print(f"{source_id}: failed: {type(exc).__name__}: {exc}")
            return False
        print(f"{source_id}: ok: {result['items']} item(s)")
        return True


async def run_all(minimum_success_rate: float) -> None:
    with session_factory()() as session:
        source_ids = list(
            session.scalars(
                select(Source.id)
                .where(Source.enabled.is_(True), Source.is_demo.is_(False))
                .order_by(Source.id)
            )
        )
    if not source_ids:
        raise SystemExit("No enabled live sources are configured")
    succeeded = sum([await run(source_id) for source_id in source_ids])
    success_rate = succeeded / len(source_ids)
    print(
        f"Validated {len(source_ids)} source(s): "
        f"{succeeded} passed, success rate {success_rate:.1%}"
    )
    if success_rate < minimum_success_rate:
        raise SystemExit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Test one configured source without ingesting")
    parser.add_argument("source_id", nargs="?")
    parser.add_argument("--all", action="store_true", dest="check_all")
    parser.add_argument("--minimum-success-rate", type=float, default=0.95)
    args = parser.parse_args()
    if not 0 <= args.minimum_success_rate <= 1:
        raise SystemExit("--minimum-success-rate must be between 0 and 1")
    if args.check_all:
        asyncio.run(run_all(args.minimum_success_rate))
    elif args.source_id:
        if not asyncio.run(run(args.source_id)):
            raise SystemExit(1)
    else:
        parser.error("provide source_id or --all")


if __name__ == "__main__":
    main()
