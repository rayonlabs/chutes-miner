# agent/client/api_client.py
from datetime import datetime, timezone
import logging
import aiohttp
from chutes_common.auth import sign_request
from chutes_common.constants import CLUSTER_ENDPOINT, RESOURCE_PURPOSE
from chutes_common.k8s import WatchEvent
from chutes_common.monitoring.models import ClusterResources, ClusterState, HeartbeatData
from chutes_common.monitoring.requests import RegisterClusterRequest, ResourceUpdateRequest
from tenacity import before_sleep_log, retry, stop_after_attempt, wait_exponential
from loguru import logger
from chutes_agent.config import settings
from typing import Optional


class ControlPlaneClient:
    """Client for communicating with the control plane API"""

    def __init__(self, control_plane_url: str):
        self.base_url = control_plane_url.rstrip("/")
        self.cluster_name = settings.cluster_name
        self._session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self):
        """Async context manager entry"""
        await self._ensure_session()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        await self.close()

    async def _ensure_session(self):
        """Ensure we have a valid session"""
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=settings.control_plane_timeout)
            self._session = aiohttp.ClientSession(timeout=timeout)

    async def close(self):
        """Close the client session"""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    async def register_cluster(self, resources: ClusterResources):
        """Send initial resource dump to control plane"""
        await self._ensure_session()

        url = f"{self.base_url}{CLUSTER_ENDPOINT}/{self.cluster_name}"

        # Serialize all Kubernetes objects
        request = RegisterClusterRequest(
            cluster_name=settings.cluster_name, initial_resources=resources
        )

        headers, payload = sign_request(request.model_dump_json(), purpose=RESOURCE_PURPOSE)
        # Need to apply json header since passing in string instead of dict
        headers["Content-Type"] = "application/json"

        async with self._session.post(url, data=payload, headers=headers) as response:
            if response.status != 200:
                error_text = await response.text()
                raise Exception(
                    f"Failed to send initial resources: {response.status} - {error_text}"
                )
            logger.info("Successfully sent initial resources")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    async def remove_cluster(self):
        """Send initial resource dump to control plane"""
        await self._ensure_session()

        url = f"{self.base_url}{CLUSTER_ENDPOINT}/{self.cluster_name}"

        headers, _ = sign_request(purpose=RESOURCE_PURPOSE)

        async with self._session.delete(url, headers=headers) as response:
            if response.status != 200:
                error_text = await response.text()
                raise Exception(f"Failed to remove cluster: {response.status} - {error_text}")
            logger.info("Successfully removed cluster")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    async def send_resource_update(self, event: WatchEvent):
        """Send resource update to control plane"""
        await self._ensure_session()

        url = f"{self.base_url}{CLUSTER_ENDPOINT}/{self.cluster_name}/resources"

        # Serialize the Kubernetes object
        request = ResourceUpdateRequest(event=event)

        headers, payload = sign_request(request.model_dump_json(), purpose=RESOURCE_PURPOSE)
        # Need to apply json header since passing in string instead of dict
        headers["Content-Type"] = "application/json"

        async with self._session.put(url, data=payload, headers=headers) as response:
            if response.status != 200:
                error_text = await response.text()
                raise Exception(f"Failed to send resource update: {response.status} - {error_text}")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    async def send_heartbeat(self, state: ClusterState):
        """Send heartbeat to control plane"""
        await self._ensure_session()

        url = f"{self.base_url}{CLUSTER_ENDPOINT}/{self.cluster_name}/health"

        heartbeat_data = HeartbeatData(
            state=state, timestamp=datetime.now(timezone.utc).isoformat()
        )

        headers, payload = sign_request(heartbeat_data.model_dump_json(), purpose=RESOURCE_PURPOSE)
        # Need to apply json header since passing in string instead of dict
        headers["Content-Type"] = "application/json"

        async with self._session.put(url, data=payload, headers=headers) as response:
            if response.status != 200:
                error_text = await response.text()
                raise Exception(f"Failed to send heartbeat: {response.status} - {error_text}")
            logger.debug("Heartbeat sent successfully")
