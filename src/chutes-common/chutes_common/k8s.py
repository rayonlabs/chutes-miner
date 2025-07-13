from dataclasses import dataclass
from enum import Enum
from typing import List, Dict, Any, Optional, Union
import json
from unittest.mock import MagicMock
from kubernetes.client import V1Deployment, V1Pod, V1Service, V1Node
from pydantic import BaseModel, ConfigDict, field_validator


class WatchEventType(Enum):
    """Enumeration of watch event types."""

    ADDED = "ADDED"
    MODIFIED = "MODIFIED"
    DELETED = "DELETED"

_resource_types = {
    type(V1Deployment): "deployment",
    type(V1Service): "service",
    type(V1Pod): "pod",
    type(V1Node): "node"
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
    
    @field_validator('object', mode='before')
    @classmethod
    def validate_object(cls, v):
        """Handle both Kubernetes objects and their dict representations"""
        if isinstance(v, dict):
            # If it's a dict, we need to determine what type it should be
            # and reconstruct the appropriate Kubernetes object
            kind = v.get('kind', '')
            if kind == 'Deployment':
                return V1Deployment(**v)
            elif kind == 'Pod':
                return V1Pod(**v)
            elif kind == 'Service':
                return V1Service(**v)
            elif kind == 'Node':
                return V1Node(**v)
            else:
                # For testing or unknown types, return as-is
                return v
        return v

    @classmethod
    def from_dict(cls, event_dict: dict) -> "WatchEvent":
        """
        Create a DeploymentWatchEvent from a dictionary.

        Args:
            event_dict: Dictionary with 'type' and 'object' keys

        Returns:
            DeploymentWatchEvent instance
        """
        return cls(type=WatchEventType(event_dict["type"]), object=event_dict["object"])

    def to_dict(self) -> dict:
        """
        Convert the event to a dictionary format.

        Returns:
            Dictionary with 'type' and 'object' keys
        """
        # Serialize the Kubernetes object
        if hasattr(self.object, 'to_dict'):
            # V1Deployment has a to_dict() method
            obj_dict = self.object.to_dict()
        elif hasattr(self.object, '__dict__'):
            # Fallback for other objects
            obj_dict = vars(self.object)
        else:
            # For MagicMock in tests
            obj_dict = self.object
        
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
