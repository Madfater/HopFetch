"""Event bus throttling, delivery across threads, overflow and the SSE generator."""

from __future__ import annotations

import asyncio
import threading

from downloader import events
from downloader.events import EventBus, event_stream, format_event


def drain(queue):
    """Return every item currently queued."""
    items = []
    while not queue.empty():
        items.append(queue.get_nowait())
    return items


def test_task_updates_are_throttled_unless_forced():
    async def scenario():
        bus = EventBus(task_min_interval=10)
        sub = bus.subscribe(asyncio.get_running_loop())
        bus.publish_task({"id": "a", "n": 1})
        bus.publish_task({"id": "a", "n": 2})
        bus.publish_task({"id": "b", "n": 1})
        bus.publish_task({"id": "a", "n": 3}, force=True)
        await asyncio.sleep(0)
        return drain(sub.queue)

    assert asyncio.run(scenario()) == [
        ("task", {"id": "a", "n": 1}), ("task", {"id": "b", "n": 1}), ("task", {"id": "a", "n": 3}),
    ]


def test_publish_from_another_thread():
    async def scenario():
        bus = EventBus()
        sub = bus.subscribe(asyncio.get_running_loop())
        thread = threading.Thread(target=bus.publish_removed, args=("x",))
        thread.start()
        item = await asyncio.wait_for(sub.queue.get(), 2)
        thread.join()
        return item

    assert asyncio.run(scenario()) == ("task_removed", {"id": "x"})


def test_overflow_ends_the_stream(monkeypatch):
    monkeypatch.setattr(events, "QUEUE_SIZE", 2)

    async def scenario():
        bus = EventBus()
        sub = bus.subscribe(asyncio.get_running_loop())
        for n in range(5):
            bus.publish("storage", {"n": n})
        await asyncio.sleep(0)
        return sub.closed, drain(sub.queue)

    assert asyncio.run(scenario()) == (True, [None])


def test_event_stream_heartbeat_and_events():
    async def scenario():
        bus = EventBus()
        stream = event_stream(bus, heartbeat=0.05)
        out = [await stream.__anext__(), await stream.__anext__()]
        bus.publish("storage", {"free_bytes": 1})
        out.append(await stream.__anext__())
        await stream.aclose()
        return out, len(bus._subscribers)

    out, remaining = asyncio.run(scenario())
    assert out == ["retry: 3000\n\n", ": ping\n\n", 'event: storage\ndata: {"free_bytes": 1}\n\n']
    assert remaining == 0


def test_event_stream_ends_after_overflow(monkeypatch):
    monkeypatch.setattr(events, "QUEUE_SIZE", 1)

    async def scenario():
        bus = EventBus()
        stream = event_stream(bus, heartbeat=5)
        first = await stream.__anext__()
        bus.publish("storage", {"n": 1})
        bus.publish("storage", {"n": 2})
        await asyncio.sleep(0)
        rest = [chunk async for chunk in stream]
        return first, rest, len(bus._subscribers)

    assert asyncio.run(scenario()) == ("retry: 3000\n\n", [], 0)


def test_format_event_keeps_unicode():
    assert format_event("task", {"file_name": "影片"}) == 'event: task\ndata: {"file_name": "影片"}\n\n'
