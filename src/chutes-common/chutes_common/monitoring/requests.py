from typing import Annotated, Any, Dict
from chutes_common.k8s import WatchEvent
from chutes_common.k8s import ClusterResources
from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator


class SetClusterResourcesRequest(BaseModel):
    """Request to set cluster resources"""

    resources: ClusterResources = Field(
        ..., description="Intiial resources to register for this cluster"
    )

    @field_serializer("resources")
    def serialize_event(self, resources: ClusterResources) -> Dict[str, Any]:
        return resources.to_dict()

    @field_validator("resources", mode="before")
    @classmethod
    def validate_resources(cls, v: Any) -> ClusterResources:
        if isinstance(v, ClusterResources):
            return v
        if not isinstance(v, dict):
            raise ValueError("resources must be a dictionary")

        # Reconstruct the Kubernetes objects from their dictionary representations.
        # The constructor of the k8s client objects can typically take the dict.
        return ClusterResources.from_dict(v)


class ResourceUpdateRequest(BaseModel):
    """Resource update from member cluster"""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    event: WatchEvent

    @field_serializer("event")
    def serialize_event(self, event: WatchEvent) -> Dict[str, Any]:
        return event.to_dict()

    @field_validator("event", mode="before")
    @classmethod
    def validate_resources(cls, v: Any) -> ClusterResources:
        if isinstance(v, WatchEvent):
            return v

        if not isinstance(v, dict):
            raise ValueError("event must be a dictionary")

        return WatchEvent.from_dict(v)


class StartMonitoringRequest(BaseModel):
    """Request to start monitoring a cluster"""

    control_plane_url: Annotated[str, Field(min_length=1)]

    @field_validator("control_plane_url")
    @classmethod
    def validate_url(cls, v):
        if not v or not v.strip():
            raise ValueError("URL cannot be empty")
        return v
