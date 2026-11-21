"""Send events to the processing program, with a buffer and retries.

Messages go into an in-memory queue so a slow or offline receiver never blocks
the Discord connection. A background worker drains the queue and POSTs each
event, retrying on network errors and 5xx/429 responses.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp

log = logging.getLogger(__name__)

RETRYABLE_STATUSES = {408, 429, 500, 502, 503, 504}


class Forwarder:
    def __init__(
        self,
        url: str,
        secret: str | None = None,
        max_retries: int = 5,
        queue_size: int = 1000,
        base_delay: float = 1.0,
        timeout: float = 10.0,
    ) -> None:
        self.url = url
        self.secret = secret
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=queue_size)
        self._session: aiohttp.ClientSession | None = None
        self._worker: asyncio.Task[None] | None = None

    async def start(self) -> None:
        headers = {"User-Agent": "discord-message-bridge"}
        if self.secret:
            headers["X-Bridge-Secret"] = self.secret
        self._session = aiohttp.ClientSession(headers=headers, timeout=self.timeout)
        self._worker = asyncio.create_task(self._run(), name="forwarder")

    async def close(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            try:
                await self._worker
            except asyncio.CancelledError:
                pass
        if self._session is not None:
            await self._session.close()

    def submit(self, event: dict[str, Any]) -> bool:
        """Queue an event. Returns False (and drops it) if the queue is full."""
        try:
            self.queue.put_nowait(event)
            return True
        except asyncio.QueueFull:
            log.error("Forward queue full; dropping message %s", event.get("message_id"))
            return False

    async def _run(self) -> None:
        while True:
            event = await self.queue.get()
            try:
                await self.send(event)
            except Exception:  # never let one bad event kill the worker
                log.exception("Unexpected error forwarding message %s", event.get("message_id"))
            finally:
                self.queue.task_done()

    async def send(self, event: dict[str, Any]) -> bool:
        """POST one event, retrying with exponential backoff. Returns True on success."""
        assert self._session is not None, "call start() first"
        message_id = event.get("message_id")
        for attempt in range(self.max_retries + 1):
            try:
                async with self._session.post(self.url, json=event) as resp:
                    if resp.status < 300:
                        log.debug("Forwarded message %s", message_id)
                        return True
                    if resp.status not in RETRYABLE_STATUSES:
                        body = (await resp.text())[:200]
                        log.error(
                            "Receiver rejected message %s with HTTP %s: %s",
                            message_id, resp.status, body,
                        )
                        return False
                    log.warning("Receiver returned HTTP %s for message %s", resp.status, message_id)
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                log.warning("Could not reach receiver for message %s: %r", message_id, exc)

            if attempt < self.max_retries:
                await asyncio.sleep(self.base_delay * 2**attempt)

        log.error("Giving up on message %s after %d retries", message_id, self.max_retries)
        return False
