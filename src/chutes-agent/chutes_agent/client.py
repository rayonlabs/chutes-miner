# agent/client/api_client.py
from datetime import datetime, timezone
import logging
import aiohttp
import json
from chutes_common.auth import sign_request
from chutes_common.k8s import WatchEvent
from chutes_common.monitoring.models import ClusterResources, ClusterState, HeartbeatData
from chutes_common.monitoring.requests import RegisterClusterRequest, ResourceUpdateRequest
from tenacity import before_sleep_log, retry, stop_after_attempt, wait_exponential
from loguru import logger
from chutes_agent.config import settings
from typing import Dict, Any, List
from chutes_common.constants import CLUSTER_ENDPOINT, RESOURCE_PURPOSE

class ControlPlaneClient:
    """Client for communicating with the control plane API"""
    
    def __init__(self, control_plane_url: str):
        self.base_url = control_plane_url.rstrip('/')
        self.cluster_name = settings.cluster_name
    
    def _serialize_k8s_object(self, obj) -> Dict[str, Any]:
        """Convert Kubernetes object to JSON-serializable dict"""
        # Use the object's to_dict() method if available, otherwise convert to dict
        if hasattr(obj, 'to_dict'):
            return obj.to_dict()
        elif hasattr(obj, '__dict__'):
            return self._convert_object_dict(obj.__dict__)
        else:
            return str(obj)
    
    def _convert_object_dict(self, obj_dict: Dict) -> Dict[str, Any]:
        """Recursively convert object dict to JSON-serializable format"""
        result = {}
        for key, value in obj_dict.items():
            if key.startswith('_'):
                continue
            
            if hasattr(value, 'to_dict'):
                result[key] = value.to_dict()
            elif isinstance(value, dict):
                result[key] = self._convert_object_dict(value)
            elif isinstance(value, list):
                result[key] = [
                    item.to_dict() if hasattr(item, 'to_dict') else item 
                    for item in value
                ]
            elif hasattr(value, 'isoformat'):  # datetime objects
                result[key] = value.isoformat()
            else:
                result[key] = value
        
        return result
    
    @retry(stop=stop_after_attempt(3),
           wait=wait_exponential(multiplier=1, min=4, max=10),
           before_sleep=before_sleep_log(logger, logging.WARNING),
           reraise=True)
    async def register_cluster(self, resources: ClusterResources):
        """Send initial resource dump to control plane"""
        url = f"{self.base_url}{CLUSTER_ENDPOINT}/{self.cluster_name}"
        
        # Serialize all Kubernetes objects
        request = RegisterClusterRequest(
            cluster_name=settings.cluster_name,
            initial_resources=resources
        )
        
        headers, payload = sign_request(request.model_dump_json(), purpose=RESOURCE_PURPOSE)
        # Need to apply json header since passing in string instead of dict
        headers["Content-Type"] = "application/json"
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url, 
                data=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=settings.control_plane_timeout)
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise Exception(f"Failed to send initial resources: {response.status} - {error_text}")
                logger.info("Successfully sent initial resources")

    @retry(stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True)
    async def remove_cluster(self):
        """Send initial resource dump to control plane"""
        url = f"{self.base_url}{CLUSTER_ENDPOINT}/{self.cluster_name}"
        
        headers, _ = sign_request(purpose=RESOURCE_PURPOSE)

        async with aiohttp.ClientSession() as session:
            async with session.delete(
                url,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=settings.control_plane_timeout)
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise Exception(f"Failed to remove cluster: {response.status} - {error_text}")
                logger.info("Successfully removed cluster")
    
    @retry(stop=stop_after_attempt(3),
           wait=wait_exponential(multiplier=1, min=4, max=10),
           before_sleep=before_sleep_log(logger, logging.WARNING),
           reraise=True)
    async def send_resource_update(self, event: WatchEvent):
        """Send resource update to control plane"""
        url = f"{self.base_url}{CLUSTER_ENDPOINT}/{self.cluster_name}/resources"
        
        # Serialize the Kubernetes object
        request = ResourceUpdateRequest(event=event)
        
        headers, payload = sign_request(request.model_dump_json(), purpose=RESOURCE_PURPOSE)
        # Need to apply json header since passing in string instead of dict
        headers["Content-Type"] = "application/json"

        async with aiohttp.ClientSession() as session:
            async with session.put(
                url, 
                data=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=settings.control_plane_timeout)
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise Exception(f"Failed to send resource update: {response.status} - {error_text}")
    
    @retry(stop=stop_after_attempt(3),
           wait=wait_exponential(multiplier=1, min=4, max=10),
           before_sleep=before_sleep_log(logger, logging.WARNING),
           reraise=True)
    async def send_heartbeat(self, state: ClusterState):
        """Send heartbeat to control plane"""
        url = f"{self.base_url}{CLUSTER_ENDPOINT}/{self.cluster_name}/health"
        
        heartbeat_data = HeartbeatData(
            state=state,
            timestamp=datetime.now(timezone.utc).isoformat()
        )

        headers, payload = sign_request(heartbeat_data.model_dump_json(), purpose=RESOURCE_PURPOSE)
        # Need to apply json header since passing in string instead of dict
        headers["Content-Type"] = "application/json"

        async with aiohttp.ClientSession() as session:
            async with session.put(
                url, 
                data=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=settings.control_plane_timeout)
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    raise Exception(f"Failed to send heartbeat: {response.status} - {error_text}")
                logger.debug("Heartbeat sent successfully")