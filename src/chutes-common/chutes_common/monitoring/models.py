from datetime import datetime
import json
from types import SimpleNamespace
from typing import Generator, Optional, Tuple, Union
from pydantic import BaseModel, ConfigDict, Field, field_validator
from enum import Enum
from kubernetes_asyncio.client import V1Deployment, V1Service, V1Pod, V1Node, ApiClient
from yaml import serialize

class MonitoringState(str, Enum):
    """Monitoring status enumeration"""
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    ERROR = "error"

class MonitoringStatus(BaseModel):
    """Current monitoring status"""
    cluster_id: Optional[str] = None
    state: str  # "stopped", "starting", "running", "error"
    error_message: Optional[str] = None
    last_heartbeat: Optional[str] = None

class ClusterState(str, Enum):
    """Cluster monitoring state enumeration"""
    INACTIVE = "inactive"
    STARTING = "starting"
    ACTIVE = "active"
    ERROR = "error"
    UNHEALTHY = "unhealthy"

class ClusterStatus(BaseModel):
    """Cluster monitoring status"""
    cluster_name: str
    state: ClusterState
    last_heartbeat: Optional[datetime] = None
    error_message: Optional[str] = None
    heartbeat_failures: int = 0

    @property
    def is_healthy(self):
        return self.state in [ClusterState.ACTIVE, ClusterState.STARTING]

class ClusterResources(BaseModel):
    """Cluster monitoring status"""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    deployments: list[V1Deployment] = []
    services: list[V1Service] = []
    pods: list[V1Pod] = []
    nodes:list[V1Node] = []

    @classmethod
    def from_dict(cls, v: dict) -> "ClusterResources":
        api_client = ApiClient()

        return cls(
            deployments=api_client.deserialize(
                SimpleNamespace(data=json.dumps(v.get('deployments', []))), 
                'list[V1Deployment]'
            ),
            services=api_client.deserialize(
                SimpleNamespace(data=json.dumps(v.get('services', []))), 
                'list[V1Service]'
            ),
            pods=api_client.deserialize(
                SimpleNamespace(data=json.dumps(v.get('pods', []))), 
                'list[V1Pod]'
            ),
            nodes=api_client.deserialize(
                SimpleNamespace(data=json.dumps(v.get('nodes', []))), 
                'list[V1Node]'
            )
        )

    def to_dict(self) -> dict:
        """Convert the cluster resources to a dictionary representation"""
        result = {}
        api_client = ApiClient()

        for pod in self.pods:
            pod.to_dict(serialize=True)

        for field_name, field_value in self:
            if isinstance(field_value, list):
                # Convert each Kubernetes object to dict using its to_dict method
                result[field_name] = [
                    api_client.sanitize_for_serialization(obj)
                    for obj in field_value
                ]
            else:
                result[field_name] = api_client.sanitize_for_serialization(field_value)
                
        return result

    def items(self) -> Generator[Tuple[str, list[Union[V1Deployment, V1Service, V1Pod, V1Node]]], None, None]:
        yield "deployment", self.deployments
        yield "services", self.services
        yield "pods", self.pods
        yield "nodes", self.nodes

class HeartbeatData(BaseModel):
    """Heartbeat data from member cluster"""
    state: ClusterState
    timestamp: Optional[str] = None