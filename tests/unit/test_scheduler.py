from __future__ import annotations

import asyncio
from pathlib import Path

from news_claws.config import Settings
from news_claws.scheduler import collection_loop


def test_collection_loop_stops_without_waiting_when_signaled() -> None:
    settings = Settings(
        app_env="test",
        database_url="sqlite:///:memory:",
        admin_token="test-token",
        trendradar_mcp_url="http://127.0.0.1:3333/mcp",
        trendradar_enabled=False,
        search_provider="disabled",
        llm_provider="deterministic",
        llm_model="rules-v1",
        daily_llm_budget=0,
        data_retention_days=365,
        seed_demo=False,
        log_level="WARNING",
        allowed_hosts=("testserver",),
        max_request_bytes=1_048_576,
        scheduler_enabled=True,
        scheduler_interval_seconds=60,
        scheduler_max_items=20,
        outbound_user_agent="NewsClaws/0.1 (test suite)",
        project_root=Path.cwd(),
    )

    async def scenario() -> None:
        stop_event = asyncio.Event()
        stop_event.set()
        await asyncio.wait_for(
            collection_loop(settings, stop_event, asyncio.Lock()),
            timeout=0.5,
        )

    asyncio.run(scenario())
