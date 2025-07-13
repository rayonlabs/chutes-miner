from datetime import datetime
import json
from typing import Generator, Optional, Tuple, Union
from pydantic import BaseModel, ConfigDict, Field, field_validator
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

    @classmethod
    def _validate_k8s_objects(cls, v, target_type):
        """Generic method to handle Kubernetes objects and their dict representations"""
        if not isinstance(v, list):
            return v
            
        objects = []
        for item in v:
            if isinstance(item, dict):
                objects.append(target_type(**item))
            else:
                objects.append(item)
        return objects

    @field_validator('deployments', mode='before')
    @classmethod
    def validate_deployments(cls, v):
        return cls._validate_k8s_objects(v, V1Deployment)
    
    @field_validator('services', mode='before')
    @classmethod
    def validate_services(cls, v):
        return cls._validate_k8s_objects(v, V1Service)
    
    @field_validator('pods', mode='before')
    @classmethod
    def validate_pods(cls, v):
        return cls._validate_k8s_objects(v, V1Pod)
    
    @field_validator('nodes', mode='before')
    @classmethod
    def validate_nodes(cls, v):
        return cls._validate_k8s_objects(v, V1Node)
    
    def to_dict(self) -> dict:
        """Convert the cluster resources to a dictionary representation"""
        result = {}
        
        for field_name, field_value in self:
            if isinstance(field_value, list):
                # Convert each Kubernetes object to dict using its to_dict method
                result[field_name] = [
                    obj.to_dict() if hasattr(obj, 'to_dict') else obj
                    for obj in field_value
                ]
            else:
                result[field_name] = field_value
                
        return result

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