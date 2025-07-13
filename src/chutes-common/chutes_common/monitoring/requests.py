from typing import Annotated, Any, Dict
from chutes_common.k8s import WatchEvent
from chutes_common.monitoring.models import ClusterResources
from pydantic import BaseModel, Field, field_serializer, field_validator


class RegisterClusterRequest(BaseModel):
    """Request to register and start monitoring a cluster"""
    cluster_name: str = Field(min_length=1, description="Unique cluster name")
    initial_resources: ClusterResources = Field(..., description="Intiial resources to register for this cluster")

    @field_serializer('initial_resources')
    def serialize_event(self, initial_resources: ClusterResources) -> Dict[str, Any]:
        return initial_resources.to_dict()

class ResourceUpdateRequest(BaseModel):
    """Resource update from member cluster"""
    event: WatchEvent

    @field_serializer('event')
    def serialize_event(self, event: WatchEvent) -> Dict[str, Any]:
        return event.to_dict()

class StartMonitoringRequest(BaseModel):
    """Request to start monitoring a cluster"""
    control_plane_url: Annotated[str, Field(min_length=1)]
    
    @field_validator('control_plane_url')
    @classmethod
    def validate_url(cls, v):
        if not v or not v.strip():
            raise ValueError('URL cannot be empty')
        return v