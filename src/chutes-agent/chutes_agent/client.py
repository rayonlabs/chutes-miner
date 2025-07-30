# agent/client/api_client.py
from datetime import datetime, timezone
import json
import logging
import aiohttp
from chutes_common.auth import sign_request
from chutes_common.constants import CLUSTER_ENDPOINT, MONITORING_PURPOSE
from chutes_common.k8s import WatchEvent, ClusterResources
from chutes_common.monitoring.models import ClusterState, HeartbeatData
from chutes_common.monitoring.requests import SetClusterResourcesRequest, ResourceUpdateRequest
from chutes_common.exceptions import ClusterConflictException, ClusterNotFoundException, ServerNotFoundException
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

    async def register_cluster(self, resources: ClusterResources):
        """Send initial resource dump to control plane"""
        await self._ensure_session()

        url = f"{self.base_url}{CLUSTER_ENDPOINT}/{self.cluster_name}"

        # Serialize all Kubernetes objects
        request = SetClusterResourcesRequest(
            resources=resources
        )

        headers, payload = sign_request(request.model_dump_json(), purpose=MONITORING_PURPOSE, management=True)
        # Need to apply json header since passing in string instead of dict
        headers["Content-Type"] = "application/json"

        async with self._session.post(url, data=payload, headers=headers) as response:
            if response.status != 200:
                if response.status == 409:
                    raise ClusterConflictException()
                elif response.status == 404:
                    raise ServerNotFoundException()
                else:
                    try:
                        error_json = await response.json()
                        error = json.dumps(error_json)
                    except:
                        error = await response.text()
                    raise Exception(
                        f"Failed to send initial resources: {response.status} - {error}"
                    )
            
            logger.info("Successfully sent initial resources")


    async def remove_cluster(self):
        """Send initial resource dump to control plane"""
        await self._ensure_session()

        url = f"{self.base_url}{CLUSTER_ENDPOINT}/{self.cluster_name}"

        headers, _ = sign_request(purpose=MONITORING_PURPOSE, management=True)

        async with self._session.delete(url, headers=headers) as response:
            if response.status != 200:
                try:
                    error_json = await response.json()
                    error = json.dumps(error_json)
                except:
                    error = await response.text()
                raise Exception(f"Failed to remove cluster: {response.status} - {error}")
            logger.info("Successfully removed cluster")

    async def set_cluster_resources(self, resources: ClusterResources):
        """Send resource update to control plane"""
        await self._ensure_session()

        url = f"{self.base_url}{CLUSTER_ENDPOINT}/{self.cluster_name}/resources"

        # Serialize the Kubernetes object
        request = SetClusterResourcesRequest(resources=resources)

        headers, payload = sign_request(request.model_dump_json(), purpose=MONITORING_PURPOSE, management=True)
        # Need to apply json header since passing in string instead of dict
        headers["Content-Type"] = "application/json"

        async with self._session.put(url, data=payload, headers=headers) as response:
            if response.status != 200:
                if response.status == 404:
                    raise ServerNotFoundException()
                elif response.status == 410:
                    raise ClusterNotFoundException()
                else:
                    try:
                        error_json = await response.json()
                        error = json.dumps(error_json)
                    except:
                        error = await response.text()
                    raise Exception(f"Failed to set cluster resources: {response.status} - {error}")

    async def send_resource_update(self, event: WatchEvent):
        """Send resource update to control plane"""
        await self._ensure_session()

        url = f"{self.base_url}{CLUSTER_ENDPOINT}/{self.cluster_name}/resources"

        # Serialize the Kubernetes object
        request = ResourceUpdateRequest(event=event)

        headers, payload = sign_request(request.model_dump_json(), purpose=MONITORING_PURPOSE, management=True)
        # Need to apply json header since passing in string instead of dict
        headers["Content-Type"] = "application/json"

        async with self._session.patch(url, data=payload, headers=headers) as response:
            if response.status != 200:
                try:
                    error_json = await response.json()
                    error = json.dumps(error_json)
                except:
                    error = await response.text()
                raise Exception(f"Failed to send resource update: {response.status} - {error}")

    async def send_heartbeat(self, state: ClusterState):
        """Send heartbeat to control plane"""
        await self._ensure_session()

        url = f"{self.base_url}{CLUSTER_ENDPOINT}/{self.cluster_name}/health"

        heartbeat_data = HeartbeatData(
            state=state, timestamp=datetime.now(timezone.utc).isoformat()
        )

        headers, payload = sign_request(heartbeat_data.model_dump_json(), purpose=MONITORING_PURPOSE, management=True)
        # Need to apply json header since passing in string instead of dict
        headers["Content-Type"] = "application/json"

        async with self._session.put(url, data=payload, headers=headers) as response:
            if response.status != 200:
                try:
                    error_json = await response.json()
                    error = json.dumps(error_json)
                except:
                    error = await response.text()
                raise Exception(f"Failed to send heartbeat: {response.status} - {error}")
            logger.debug("Heartbeat sent successfully")
