from datetime import datetime
import json
from typing import Generator, Optional, Tuple, Union
from pydantic import BaseModel, ConfigDict, Field
from enum import Enum
from kubernetes.client import V1Deployment, V1Service, V1Pod, V1Node

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

class ClusterResources(BaseModel):
    """Cluster monitoring status"""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    deployments: list[V1Deployment] = []
    services: list[V1Service] = []
    pods: list[V1Pod] = []
    nodes:list[V1Node] = []

    # def json(self, **kwargs) -> str:
    #     """Custom JSON serialization that handles K8s objects"""
    #     data = self.model_dump(**kwargs)
        
    #     # Convert K8s objects to dictionaries
    #     for field_name in ['deployments', 'services', 'pods', 'nodes']:
    #         if field_name in data:
    #             serialized_items = []
    #             for item in data[field_name]:
    #                 if hasattr(item, 'to_dict'):
    #                     serialized_items.append(item.to_dict())
    #                 elif hasattr(item, '__dict__'):
    #                     serialized_items.append(item.__dict__)
    #                 else:
    #                     serialized_items.append(item)
    #             data[field_name] = serialized_items

    #     return json.dumps(data, default=str)

    def items(self) -> Generator[Tuple[str, list[Union[V1Deployment, V1Service, V1Pod, V1Node]]], None, None]:
        yield "deployment", self.deployments
        yield "services", self.services
        yield "pods", self.pods
        yield "nodes", self.nodes

class HeartbeatData(BaseModel):
    """Heartbeat data from member cluster"""
    status: ClusterState
    cluster_name: str
    timestamp: Optional[str] = None