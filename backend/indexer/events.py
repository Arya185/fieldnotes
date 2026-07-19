"""Run-scoped SSE event hubs for indexing progress."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4


@dataclass
class EventStreamHub:
    """Fan-out hub with replay for current indexing run."""

    subscribers: list[asyncio.Queue[str | None]] = field(default_factory=list)
    replay_events: list[str] = field(default_factory=list)
    closed: bool = False

    def subscribe(self) -> asyncio.Queue[str | None]:
        queue: asyncio.Queue[str | None] = asyncio.Queue()
        for event in self.replay_events:
            queue.put_nowait(event)
        if self.closed:
            queue.put_nowait(None)
        self.subscribers.append(queue)
        return queue

    def publish(self, payload: dict[str, Any]) -> None:
        encoded = json.dumps(payload)
        self.replay_events.append(encoded)
        for subscriber in list(self.subscribers):
            subscriber.put_nowait(encoded)

    def close(self) -> None:
        self.closed = True
        for subscriber in list(self.subscribers):
            subscriber.put_nowait(None)


@dataclass
class RunManager:
    """Manage per-run event hubs."""

    runs: dict[str, EventStreamHub] = field(default_factory=dict)

    def create_run(self) -> tuple[str, EventStreamHub]:
        run_id = str(uuid4())
        hub = EventStreamHub()
        self.runs[run_id] = hub
        return run_id, hub

    def get_hub(self, run_id: str) -> EventStreamHub | None:
        return self.runs.get(run_id)


run_manager = RunManager()
