from __future__ import annotations

import asyncio
import logging

from .config import Settings
from .database import session_factory
from .notifications import dispatch_pending_notifications
from .services import pull_sources

logger = logging.getLogger("news_claws.scheduler")


async def run_collection_cycle(
    settings: Settings,
    collection_lock: asyncio.Lock,
) -> list[dict[str, object]]:
    async with collection_lock:
        with session_factory()() as session:
            results = await pull_sources(
                session,
                settings,
                source_ids=[],
                max_items_per_source=settings.scheduler_max_items,
            )
        if settings.notification_enabled:
            await asyncio.to_thread(_dispatch_notifications, settings)
        return results


def _dispatch_notifications(settings: Settings) -> None:
    with session_factory()() as session:
        dispatch_pending_notifications(session, settings)


async def collection_loop(
    settings: Settings,
    stop_event: asyncio.Event,
    collection_lock: asyncio.Lock,
) -> None:
    while True:
        try:
            await asyncio.wait_for(
                stop_event.wait(),
                timeout=settings.scheduler_interval_seconds,
            )
            return
        except TimeoutError:
            pass

        try:
            results = await run_collection_cycle(settings, collection_lock)
            succeeded = sum(item.get("status") == "succeeded" for item in results)
            logger.info(
                "scheduled_collection_finished sources=%s succeeded=%s",
                len(results),
                succeeded,
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("scheduled_collection_failed")
