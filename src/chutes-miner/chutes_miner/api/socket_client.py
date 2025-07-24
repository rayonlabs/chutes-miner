"""
Miner websockets.
"""

import orjson as json
from socketio import AsyncClient
from loguru import logger
from chutes_common.auth import sign_request
from chutes_miner.api.config import settings


class SocketClient:
    def __init__(self, url: str, validator: str):
        """
        Constructor.
        """
        self.url = url
        self.validator = validator
        self.sio = AsyncClient()
        self.setup_handlers()

    def setup_handlers(self):
        """
        Configure all of the socket.io event handlers.
        """

        @self.sio.event
        async def connect():
            """
            Connection to validator established.
            """
            logger.success(f"Successfully connected to validator websocket: {self.url}")
            await self.authenticate()

        @self.sio.event
        async def disconnect():
            """
            Miner disconnected.
            """
            logger.warning(f"Socket disconnected: {self.url}")

        @self.sio.event
        async def auth_success(_):
            """
            Authentication successful.
            """
            logger.success(f"Authentication successful: {self.url}")

        @self.sio.event
        async def auth_failed(data):
            """
            Authentication failure.
            """
            logger.error(f"Authentication failed [url={self.url}]: {data}")
            await self.sio.disconnect()

        @self.sio.event
        async def miner_broadcast(data):
            """
            Broadcast events from the validator. Really here we only care about
            relaying that event to our own internal redis pubsub, since that's
            where the magic happens.
            """
            logger.info(f"Received broadcast to miners: {data}")
            reason = data.get("reason")
            if reason not in (
                "gpu_verified",
                "chute_deleted",
                "chute_created",
                "bounty_change",
                "image_created",
                "image_deleted",
                "image_updated",
                "instance_created",
                "instance_deleted",
                "instance_verified",
                "instance_activated",
                "rolling_update",
                "job_created",
                "job_deleted",
                "chute_updated",
            ):
                logger.warning(f"Ignoring invalid broadcast: {data}")
                return
            data["data"].update({"validator": self.validator})
            await settings.redis_client.publish(
                "miner_events",
                json.dumps(
                    {
                        "event_type": reason,
                        "event_data": data["data"],
                    }
                ).decode(),
            )

    async def authenticate(self):
        """
        Authenticate using hotkey and signature, always the first
        payload after connections are established.
        """
        try:
            headers, _ = sign_request(purpose="sockets")
            await self.sio.emit("authenticate", headers)
            logger.debug(f"Sent authentication request: {headers=}")
        except Exception as e:
            logger.error(f"Authentication error: {e}")
            await self.sio.disconnect()

    async def connect_and_run(self):
        """
        Connect to server and run the client
        """
        try:
            await self.sio.connect(
                self.url,
                wait_timeout=10,
                wait=True,
                transports=["websocket"],
            )
            await self.sio.wait()
        except Exception as e:
            logger.error(f"Client error: {e}")
        finally:
            await self.sio.disconnect()
