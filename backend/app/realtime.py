"""Real-time hub: per-user WebSocket fan-out, with optional Redis for multi-worker setups.

* No Redis  -> in-memory delivery (works with a single uvicorn worker).
* Redis     -> publish/subscribe fan-out across workers + presence keys with a TTL.
  If REDIS_URL is set but unreachable at startup we log a warning and fall back to in-memory.

`publish()` is synchronous and thread-safe, so the (sync) REST routes can call it right after
`db.commit()`. Delivery is best effort: the database stays the source of truth, and clients
re-fetch over REST after (re)connecting. A failed notification never fails the API call.

No FastAPI imports here, so this module is unit-testable on its own.
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Iterable

log = logging.getLogger("realtime")

CHANNEL = "bloodmatch:events"
PRESENCE_TTL_SECONDS = 90


def _presence_key(user_id: int) -> str:
    return f"presence:user:{user_id}"


class Hub:
    def __init__(self) -> None:
        self._conns: dict[int, set[Any]] = defaultdict(set)   # user_id -> websockets on THIS worker
        self._loop: asyncio.AbstractEventLoop | None = None
        self._redis_pub = None       # sync redis client (publish, presence)
        self._redis_async = None     # asyncio redis client (subscribe)
        self._listener: asyncio.Task | None = None

    # ------------------------------------------------------------ lifecycle
    async def start(self, redis_url: str | None = None) -> None:
        self._loop = asyncio.get_running_loop()
        if not redis_url:
            log.info("Realtime hub: in-memory mode (single worker)")
            return
        try:
            import redis
            import redis.asyncio as aredis

            pub = redis.Redis.from_url(redis_url, decode_responses=True)
            await asyncio.to_thread(pub.ping)
            self._redis_pub = pub
            self._redis_async = aredis.Redis.from_url(redis_url, decode_responses=True)
            self._listener = asyncio.create_task(self._listen())
            log.info("Realtime hub: Redis mode")
        except Exception as exc:  # noqa: BLE001
            log.warning("Redis unavailable (%s); falling back to in-memory hub", exc)
            self._redis_pub = self._redis_async = None

    async def stop(self) -> None:
        if self._listener:
            self._listener.cancel()
            try:
                await self._listener
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        if self._redis_async is not None:
            await self._redis_async.aclose()
        if self._redis_pub is not None:
            self._redis_pub.close()
        self._listener = self._redis_async = self._redis_pub = None

    async def _listen(self) -> None:
        """Receive events published by any worker and deliver to sockets on this one."""
        while True:
            try:
                pubsub = self._redis_async.pubsub()
                await pubsub.subscribe(CHANNEL)
                async for msg in pubsub.listen():
                    if msg.get("type") != "message":
                        continue
                    try:
                        payload = json.loads(msg["data"])
                        await self._deliver(int(payload["user_id"]), payload["event"])
                    except (ValueError, KeyError, TypeError):
                        log.warning("Dropping malformed realtime message")
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                log.warning("Redis listener error (%s); retrying in 2s", exc)
                await asyncio.sleep(2)

    # ------------------------------------------------------------ connections
    async def connect(self, user_id: int, ws: Any) -> None:
        self._conns[user_id].add(ws)
        await self.touch(user_id)

    async def disconnect(self, user_id: int, ws: Any) -> None:
        sockets = self._conns.get(user_id)
        if sockets is not None:
            sockets.discard(ws)
            if not sockets:
                del self._conns[user_id]
        if user_id not in self._conns and self._redis_pub is not None:
            try:
                await asyncio.to_thread(self._redis_pub.delete, _presence_key(user_id))
            except Exception:  # noqa: BLE001
                pass

    async def touch(self, user_id: int) -> None:
        """Refresh presence (called on connect and on every client heartbeat)."""
        if self._redis_pub is not None:
            try:
                await asyncio.to_thread(self._redis_pub.set, _presence_key(user_id), "1",
                                        ex=PRESENCE_TTL_SECONDS)
            except Exception:  # noqa: BLE001
                pass

    def online_user_ids(self, user_ids: Iterable[int]) -> set[int]:
        ids = list(user_ids)
        if not ids:
            return set()
        if self._redis_pub is not None:
            try:
                vals = self._redis_pub.mget([_presence_key(u) for u in ids])
                return {u for u, v in zip(ids, vals) if v}
            except Exception:  # noqa: BLE001
                pass
        return {u for u in ids if u in self._conns}

    # ------------------------------------------------------------ publishing
    def publish(self, user_id: int, event: dict[str, Any]) -> None:
        """Send {type, data} to every socket of `user_id`. Sync + thread-safe. Never raises."""
        event = {**event, "ts": datetime.now(timezone.utc).isoformat()}
        try:
            if self._redis_pub is not None:
                self._redis_pub.publish(CHANNEL, json.dumps({"user_id": user_id, "event": event}))
            elif self._loop is not None and self._loop.is_running():
                asyncio.run_coroutine_threadsafe(self._deliver(user_id, event), self._loop)
        except Exception:  # noqa: BLE001
            log.exception("Failed to publish realtime event")

    async def _deliver(self, user_id: int, event: dict[str, Any]) -> None:
        sockets = self._conns.get(user_id)
        if not sockets:
            return
        dead = []
        for ws in list(sockets):
            try:
                await ws.send_json(event)
            except Exception:  # noqa: BLE001
                dead.append(ws)
        for ws in dead:
            sockets.discard(ws)
        if not sockets:
            self._conns.pop(user_id, None)


hub = Hub()
