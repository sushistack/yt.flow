import asyncio
import json
from typing import AsyncGenerator, Literal, TypedDict

_CLOSE = object()  # sentinel: unsubscribe() puts this to unblock subscribe()


class EventData(TypedDict):
    event: Literal["stage_entry", "stage_exit", "gate_pending", "run_failed"]
    data: dict  # {"run_id": str, "stage": str} or + "error" for run_failed


class SSEQueueRegistry:
    def __init__(self) -> None:
        self._queues: dict[str, asyncio.Queue] = {}

    async def subscribe(self, run_id: str) -> AsyncGenerator[str, None]:
        queue: asyncio.Queue = asyncio.Queue()
        self._queues[run_id] = queue
        try:
            while True:
                event = await queue.get()
                if event is _CLOSE:
                    break
                yield f"event: {event['event']}\ndata: {json.dumps(event['data'])}\n\n"
                if event["event"] == "run_failed":
                    break
        except asyncio.CancelledError:
            pass
        finally:
            self._queues.pop(run_id, None)

    async def publish(self, run_id: str, event: EventData) -> None:
        queue = self._queues.get(run_id)
        if queue is not None:
            await queue.put(event)

    def unsubscribe(self, run_id: str) -> None:
        # ponytail: pop first so has_subscriber() is immediately False; sentinel unblocks generator
        queue = self._queues.pop(run_id, None)
        if queue is not None:
            queue.put_nowait(_CLOSE)

    def has_subscriber(self, run_id: str) -> bool:
        return run_id in self._queues
