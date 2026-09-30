"""Server-sent events: a thread-safe bus from worker threads to every open `/api/events` stream."""

from __future__ import annotations

import asyncio
import json
import threading
import time
from typing import AsyncIterator

HEARTBEAT_SECONDS = 15.0
TASK_MIN_INTERVAL = 0.5
QUEUE_SIZE = 1000


class Subscriber:
    """One open stream: its event loop and a bounded queue of (event, data) items.

    - A None item ends the stream; it is queued when the subscriber falls too far behind.
    """

    def __init__(self, loop: asyncio.AbstractEventLoop):
        self.loop = loop
        self.queue: asyncio.Queue[tuple[str, dict] | None] = asyncio.Queue(QUEUE_SIZE)
        self.closed = False

    def put(self, item: tuple[str, dict] | None) -> None:
        """Queue `item` on the loop thread; on overflow drop the backlog and end the stream."""
        if self.closed:
            return
        try:
            self.queue.put_nowait(item)
        except asyncio.QueueFull:
            self.closed = True
            while not self.queue.empty():
                self.queue.get_nowait()
            self.queue.put_nowait(None)


class EventBus:
    """Fans events out to subscribers.

    - `publish` may be called from any thread; delivery hops onto each subscriber's loop with
      `call_soon_threadsafe`.
    - `publish_task` limits updates of one task to one per TASK_MIN_INTERVAL seconds unless
      `force` is set; forced updates are for state changes and always go out.
    """

    def __init__(self, task_min_interval: float = TASK_MIN_INTERVAL):
        self.task_min_interval = task_min_interval
        self._subscribers: set[Subscriber] = set()
        self._last_sent: dict[str, float] = {}
        self._lock = threading.Lock()

    def subscribe(self, loop: asyncio.AbstractEventLoop) -> Subscriber:
        """Register a new subscriber delivering on `loop`."""
        sub = Subscriber(loop)
        with self._lock:
            self._subscribers.add(sub)
        return sub

    def unsubscribe(self, sub: Subscriber) -> None:
        """Remove a subscriber."""
        with self._lock:
            self._subscribers.discard(sub)

    def publish(self, event: str, data: dict) -> None:
        """Send one event to every subscriber, dropping those whose loop has closed."""
        with self._lock:
            subs = list(self._subscribers)
        for sub in subs:
            try:
                sub.loop.call_soon_threadsafe(sub.put, (event, data))
            except RuntimeError:
                self.unsubscribe(sub)

    def publish_task(self, task: dict, force: bool = False) -> None:
        """Send a `task` event, throttled per task id unless `force`."""
        now = time.monotonic()
        with self._lock:
            last = self._last_sent.get(task["id"])
            if not force and last is not None and now - last < self.task_min_interval:
                return
            self._last_sent[task["id"]] = now
        self.publish("task", task)

    def publish_removed(self, task_id: str) -> None:
        """Send a `task_removed` event."""
        with self._lock:
            self._last_sent.pop(task_id, None)
        self.publish("task_removed", {"id": task_id})


def format_event(event: str, data: dict) -> str:
    """Encode one SSE message."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


async def event_stream(bus: EventBus, heartbeat: float = HEARTBEAT_SECONDS) -> AsyncIterator[str]:
    """Yield SSE text for one client until it falls behind or the server stops iterating.

    - Starts with a `retry` hint so browsers reconnect after 3 seconds.
    - Sends a `: ping` comment after `heartbeat` seconds without events. Writing it to a closed
      connection makes the server close this generator, which unsubscribes it.
    """
    sub = bus.subscribe(asyncio.get_running_loop())
    try:
        yield "retry: 3000\n\n"
        while True:
            try:
                item = await asyncio.wait_for(sub.queue.get(), heartbeat)
            except asyncio.TimeoutError:
                yield ": ping\n\n"
                continue
            if item is None:
                return
            yield format_event(*item)
    finally:
        bus.unsubscribe(sub)
