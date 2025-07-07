"""
Redis pubsub listener.
"""

import asyncio
import traceback
import orjson as json
import redis.asyncio as redis
from datetime import datetime
from typing import Optional, Dict, Callable, List
from loguru import logger
from chutes_miner.api.config import settings


class RedisListener:
    """
    Redis pubsub subscriber.
    """

    def __init__(self, channel: str = "miner_events"):
        self.channel = channel
        self.pubsub: Optional[redis.client.PubSub] = None
        self.is_running = False
        self.last_reconnect = datetime.now()
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 10
        self.base_delay = 1
        self.max_delay = 30
        self.event_handlers: Dict[str, List[Callable]] = {}

    async def start(self):
        """
        Start the listener, handling connection/timeout errors.
        """
        self.is_running = True
        while self.is_running:
            try:
                if not self.pubsub:
                    self.pubsub = settings.redis_client.pubsub()
                    await self.pubsub.subscribe(self.channel)
                    logger.info(f"Subscribed to channel: {self.channel}")
                    self.reconnect_attempts = 0
                await self._listen()
            except (redis.ConnectionError, redis.TimeoutError) as e:
                await self._handle_connection_error(e)
            except Exception as e:
                logger.error(f"Unexpected error in redis listener: {e}")
                await self._handle_connection_error(e)

    async def stop(self):
        """
        Gracefully stop the listener.
        """
        self.is_running = False
        if self.pubsub:
            await self.pubsub.unsubscribe(self.channel)
            await self.pubsub.close()
            self.pubsub = None
        logger.info("Redis listener stopped")

    def on_event(self, event_type: str):
        """
        Decorator to listen for certain event types.
        """

        def decorator(func: Callable):
            if event_type not in self.event_handlers:
                self.event_handlers[event_type] = []
            self.event_handlers[event_type].append(func)
            return func

        return decorator

    async def _listen(self):
        """
        Main listening loop.
        """
        async for message in self.pubsub.listen():
            if not self.is_running:
                break
            if message["type"] == "message":
                try:
                    data = json.loads(message["data"].decode())
                    event_type = data.get("event_type")
                    logger.info(f"Received {event_type=} with {data=}")
                    if event_type in self.event_handlers:
                        await asyncio.gather(
                            *[
                                handler(data["event_data"])
                                for handler in self.event_handlers[event_type]
                            ]
                        )
                except Exception as exc:
                    logger.error(f"Error processing message: {exc}\n{traceback.format_exc()}")

    async def _handle_connection_error(self, error):
        """
        Handle connection errors with exponential backoff.
        """
        self.reconnect_attempts += 1
        if self.reconnect_attempts > self.max_reconnect_attempts:
            logger.error("Max reconnection attempts reached. Stopping listener.")
            await self.stop()
            return
        delay = min(self.base_delay * (2 ** (self.reconnect_attempts - 1)), self.max_delay)
        logger.warning(
            f"Redis connection error: {error}, attempt {self.reconnect_attempts}/{self.max_reconnect_attempts}, retrying in {delay} seconds..."
        )
        if self.pubsub:
            try:
                await self.pubsub.close()
            except Exception as exc:
                logger.warning(f"Redis pubsub close error: {exc}")
                pass
            self.pubsub = None
        await asyncio.sleep(delay)
