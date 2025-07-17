from datetime import datetime
from typing import Generator, Optional, Tuple, Union
from chutes_common.k8s import serializer
from pydantic import BaseModel, ConfigDict
from enum import Enum
from kubernetes_asyncio.client import V1Deployment, V1Service, V1Pod, V1Node

class ResourceType(str, Enum):

    ALL = "*"
    NODE = "node"
    DEPLOYMENT = "deployment"
    SERVICE = "service"
    POD = "pod"

class MonitoringState(str, Enum):
    """Monitoring status enumeration"""

    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    ERROR = "error"


class MonitoringStatus(BaseModel):
    """Current monitoring status"""

    cluster_id: Optional[str] = None
    state: MonitoringState  # "stopped", "starting", "running", "error"
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
    nodes: list[V1Node] = []

    @classmethod
    def from_dict(cls, v: dict) -> "ClusterResources":
        return cls(
            deployments=serializer.deserialize(v.get("deployment", []), "list[V1Deployment]"),
            services=serializer.deserialize(v.get("service", []), "list[V1Service]"),
            pods=serializer.deserialize(v.get("pod", []), "list[V1Pod]"),
            nodes=serializer.deserialize(v.get("node", []), "list[V1Node]"),
        )

    def to_dict(self) -> dict:
        """Convert the cluster resources to a dictionary representation"""
        result = {}

        for field_name, field_value in self:
            if isinstance(field_value, list):
                # Convert each Kubernetes object to dict using its to_dict method
                result[field_name] = [serializer.serialize(obj) for obj in field_value]
            else:
                result[field_name] = serializer.serialize(field_value)

        return result

    def items(
        self,
    ) -> Generator[Tuple[ResourceType, list[Union[V1Deployment, V1Service, V1Pod, V1Node]]], None, None]:
        yield ResourceType.DEPLOYMENT, self.deployments
        yield ResourceType.SERVICE, self.services
        yield ResourceType.POD, self.pods
        yield ResourceType.NODE, self.nodes


class HeartbeatData(BaseModel):
    """Heartbeat data from member cluster"""

    state: ClusterState
    timestamp: Optional[str] = None
