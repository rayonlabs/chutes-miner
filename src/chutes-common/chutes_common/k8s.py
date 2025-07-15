from dataclasses import dataclass
from enum import Enum
from types import SimpleNamespace
from typing import List, Dict, Any, Optional, Union
import json
from unittest.mock import MagicMock
from kubernetes_asyncio.client import V1Deployment, V1Pod, V1Service, V1Node
from pydantic import BaseModel, ConfigDict, field_validator
from kubernetes_asyncio.client import ApiClient

class WatchEventType(Enum):
    """Enumeration of watch event types."""

    ADDED = "ADDED"
    MODIFIED = "MODIFIED"
    DELETED = "DELETED"

_resource_types = {
    V1Deployment: "deployment",
    V1Service: "service",
    V1Pod: "pod",
    V1Node: "node"
}

class WatchEvent(BaseModel):
    """
    Represents a watch event for Kubernetes deployments.

    Attributes:
        type: The type of watch event (ADDED, MODIFIED, DELETED)
        object: The V1Deployment object from the Kubernetes API
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    type: WatchEventType
    object: Union[V1Deployment , V1Pod , V1Service , V1Node, MagicMock] # Magic Mock for testing

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

            api_client = ApiClient()
            obj = api_client.deserialize(
                    SimpleNamespace(data=json.dumps(event_dict.get('object', {}))), 
                    f'V1{kind}'
                )        

        return cls(type=WatchEventType(event_dict["type"]), object=obj)

    def to_dict(self) -> dict:
        """
        Convert the event to a dictionary format.

        Returns:
            Dictionary with 'type' and 'object' keys
        """
        api_client = ApiClient()
        obj_dict = api_client.sanitize_for_serialization(self.object)
        
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
    def resource_type(self) -> str:
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
