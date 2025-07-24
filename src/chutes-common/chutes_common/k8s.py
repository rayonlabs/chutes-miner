from enum import Enum
from types import SimpleNamespace
from typing import Any, Optional, Union
import json
from unittest.mock import MagicMock
from chutes_common.monitoring.models import ResourceType
from kubernetes_asyncio.client import V1Deployment, V1Pod, V1Service, V1Node, V1Job
from pydantic import BaseModel, ConfigDict
from kubernetes_asyncio.client import ApiClient
from typing import Generator, Optional, Tuple, Union


class K8sSerializer:
    _instance = None
    _api_client = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @property
    def api_client(self):
        if self._api_client is None:
            self._api_client = ApiClient()
        return self._api_client

    async def close(self):
        if self._api_client:
            await self._api_client.close()
            self._api_client = None

    def deserialize(self, obj: dict[str, Any], kind: str):
        obj = serializer.api_client.deserialize(SimpleNamespace(data=json.dumps(obj)), kind)

        return obj

    def serialize(self, obj: Any):
        obj_dict = serializer.api_client.sanitize_for_serialization(obj)

        return obj_dict


serializer = K8sSerializer()

# ToDo: Update to use values from ResourceType after
# resolving ciruclar dependency
_resource_types = {
    V1Deployment: "deployment", 
    V1Service: "service", 
    V1Pod: "pod", 
    V1Node: "node",
    V1Job: "job"
}

class ClusterResources(BaseModel):
    """Cluster monitoring status"""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    deployments: list[V1Deployment] = []
    services: list[V1Service] = []
    pods: list[V1Pod] = []
    nodes: list[V1Node] = []
    jobs: list[V1Job] = []

    @classmethod
    def from_dict(cls, v: dict) -> "ClusterResources":
        return cls(
            deployments=serializer.deserialize(v.get("deployments", []), "list[V1Deployment]"),
            services=serializer.deserialize(v.get("services", []), "list[V1Service]"),
            pods=serializer.deserialize(v.get("pods", []), "list[V1Pod]"),
            nodes=serializer.deserialize(v.get("nodes", []), "list[V1Node]"),
            jobs=serializer.deserialize(v.get("jobs", []), "list[V1Job]"),
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
    ) -> Generator[
        Tuple[ResourceType, list[Union[V1Deployment, V1Service, V1Pod, V1Node]]], None, None
    ]:
        yield ResourceType.DEPLOYMENT, self.deployments
        yield ResourceType.SERVICE, self.services
        yield ResourceType.POD, self.pods
        yield ResourceType.NODE, self.nodes
        yield ResourceType.JOB, self.jobs

class WatchEventType(Enum):
    """Enumeration of watch event types."""

    ADDED = "ADDED"
    MODIFIED = "MODIFIED"
    DELETED = "DELETED"


class WatchEvent(BaseModel):
    """
    Represents a watch event for Kubernetes deployments.

    Attributes:
        type: The type of watch event (ADDED, MODIFIED, DELETED)
        object: The V1Deployment object from the Kubernetes API
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    type: WatchEventType
    object: Union[V1Deployment, V1Pod, V1Service, V1Node, V1Job, MagicMock]  # Magic Mock for testing

    @classmethod
    def from_dict(cls, event_dict: dict) -> "WatchEvent":
        """
        Create a DeploymentWatchEvent from a dictionary.

        Args:
            event_dict: Dictionary with 'type' and 'object' keys

        Returns:
            DeploymentWatchEvent instance
        """
        obj = event_dict.get("object", {})
        if isinstance(obj, dict):
            kind = obj.get("kind", "")

            if not kind:
                raise ValueError("event_dict object is not of kind Deployment, Pod, Service, Node")

            obj = serializer.deserialize(event_dict.get("object", {}), f"V1{kind}")

        return cls(type=WatchEventType(event_dict["type"]), object=obj)

    def to_dict(self) -> dict:
        """
        Convert the event to a dictionary format.

        Returns:
            Dictionary with 'type' and 'object' keys
        """
        obj_dict = serializer.serialize(self.object)

        return {"type": self.type.value, "object": obj_dict}

    @property
    def is_added(self) -> bool:
        """Check if this is an ADDED event."""
        return self.type == WatchEventType.ADDED

    @property
    def is_modified(self) -> bool:
        """Check if this is a MODIFIED event."""
        return self.type == WatchEventType.MODIFIED

    @property
    def is_deleted(self) -> bool:
        """Check if this is a DELETED event."""
        return self.type == WatchEventType.DELETED

    @property
    def obj_type(self) -> Optional[str]:
        """Get the deployment name from the object."""
        return self.object.kind if self.object.kind else "unknown"

    @property
    def obj_name(self) -> Optional[str]:
        """Get the deployment name from the object."""
        return self.object.metadata.name if self.object.metadata else None

    @property
    def obj_namespace(self) -> Optional[str]:
        """Get the deployment namespace from the object."""
        return self.object.metadata.namespace if self.object.metadata else None

    @property
    def obj_uid(self) -> Optional[str]:
        """Get the deployment UID from the object."""
        return self.object.metadata.uid if self.object.metadata else None

    @property
    def k8s_resource_type(self) -> str:
        return _resource_types.get(type(self.object), "unknown")

    @property
    def is_deployement(self) -> bool:
        return isinstance(self.object, V1Deployment)

    @property
    def is_pod(self) -> bool:
        return isinstance(self.object, V1Pod)

    @property
    def is_service(self) -> bool:
        return isinstance(self.object, V1Service)

    def __str__(self) -> str:
        """String representation of the event."""
        name = self.obj_name or "unknown"
        namespace = self.obj_namespace or "unknown"
        return f"DeploymentWatchEvent({self.type.value}, {namespace}/{name})"

    def __repr__(self) -> str:
        """Detailed string representation of the event."""
        return (
            f"WatchEvent(type={self.type.value}, "
            f"name={self.obj_name}, "
            f"namespace={self.obj_namespace}, "
            f"uid={self.obj_uid})"
        )
