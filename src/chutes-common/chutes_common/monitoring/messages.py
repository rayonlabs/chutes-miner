from datetime import datetime
from typing import Any

from chutes_common.k8s import WatchEvent, WatchEventType


class ResourceChangeMessage:
    def __init__(self, cluster: str, event: WatchEvent, timestamp: datetime):
        self.cluster = cluster
        self.event = event
        self.timestamp = timestamp

    @classmethod
    def from_dict(cls, v: dict[str, Any]) -> "ResourceChangeMessage":
        return cls(
            cluster=v.get("cluster"),
            event=WatchEvent.from_dict(v.get("event")),
            timestamp=datetime.strptime(v.get("timestamp"), "%Y-%m-%dT%H:%M:%S.%f%z"),
        )

    def to_dict(self):
        return {
            "cluster": self.cluster,
            "event": self.event.to_dict(),
            "timestamp": self.timestamp.isoformat(),
        }

class ClusterChangeMessage:
    def __init__(self, cluster: str, event_type: WatchEventType, timestamp: datetime):
        self.cluster = cluster
        self.event_type = event_type
        self.timestamp = timestamp

    @classmethod
    def from_dict(cls, v: dict[str, Any]) -> "ResourceChangeMessage":
        return cls(
            cluster=v.get("cluster"),
            event_type=WatchEventType[(v.get("event_type"))],
            timestamp=datetime.strptime(v.get("timestamp"), "%Y-%m-%dT%H:%M:%S.%f%z"),
        )

    def to_dict(self):
        return {
            "cluster": self.cluster,
            "event_type": self.event_type.value,
            "timestamp": self.timestamp.isoformat(),
        }
