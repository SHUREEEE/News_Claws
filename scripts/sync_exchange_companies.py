from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

from news_claws.company_registry import CompanyRecord, upsert_company_records
from news_claws.database import session_factory

MAX_CATALOG_BYTES = 50_000_000


def _stable_id(market: str, ticker: str) -> str:
    normalized_market = re.sub(r"[^a-z0-9]+", "_", market.casefold()).strip("_")
    normalized_ticker = re.sub(r"[^a-z0-9]+", "_", ticker.casefold()).strip("_")
    if not normalized_market or not normalized_ticker:
        raise ValueError("Market and ticker must contain letters or digits")
    return f"exchange_{normalized_market}_{normalized_ticker}"


def load_exchange_csv(
    path: Path,
    *,
    market: str,
    country: str,
    ticker_column: str,
    name_column: str,
    alias_columns: list[str],
    encoding: str,
) -> list[CompanyRecord]:
    if not path.is_file():
        raise ValueError(f"Catalog file does not exist: {path}")
    if path.stat().st_size > MAX_CATALOG_BYTES:
        raise ValueError("Exchange company catalog exceeds the 50 MB limit")
    records: list[CompanyRecord] = []
    with path.open("r", encoding=encoding, newline="") as handle:
        reader = csv.DictReader(handle)
        required = {ticker_column, name_column, *alias_columns}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"Catalog is missing columns: {sorted(missing)}")
        for row in reader:
            ticker = (row.get(ticker_column) or "").strip().upper()
            name = (row.get(name_column) or "").strip()
            if not ticker or not name:
                continue
            aliases = tuple(
                value
                for column in alias_columns
                if (value := (row.get(column) or "").strip()) and value != name
            )
            records.append(
                CompanyRecord(
                    stable_id=_stable_id(market, ticker),
                    canonical_name=name,
                    country=country,
                    market=market,
                    ticker=ticker,
                    aliases=aliases,
                )
            )
    if not records:
        raise ValueError("Exchange company catalog did not contain valid rows")
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description="Import an official exchange company CSV export")
    parser.add_argument("catalog", type=Path)
    parser.add_argument(
        "--market",
        required=True,
        help="Stable market code, e.g. SSE, SZSE, HKEX",
    )
    parser.add_argument("--country", required=True, help="ISO-style country/region code")
    parser.add_argument("--ticker-column", required=True)
    parser.add_argument("--name-column", required=True)
    parser.add_argument("--alias-column", action="append", default=[])
    parser.add_argument("--encoding", default="utf-8-sig")
    args = parser.parse_args()

    records = load_exchange_csv(
        args.catalog,
        market=args.market,
        country=args.country,
        ticker_column=args.ticker_column,
        name_column=args.name_column,
        alias_columns=args.alias_column,
        encoding=args.encoding,
    )
    with session_factory()() as session:
        count = upsert_company_records(session, records)
    print(f"Synchronized {count} {args.market.upper()} companies")


if __name__ == "__main__":
    main()
