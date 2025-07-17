# app/cache/redis_client.py
from datetime import datetime, timezone
from chutes_common.k8s import WatchEvent, serializer
from chutes_common.monitoring.messages import ResourceChangeMessage
from chutes_common.monitoring.models import ClusterResources, ClusterState, ClusterStatus, ResourceType
import json
from typing import Optional, Dict, Any, List
from chutes_common.settings import RedisSettings
from loguru import logger
# from chutes_monitor.config import settings
from redis import Redis
from redis.client import PubSub
from referencing import Resource


class MonitoringRedisClient:
    """Async Redis client for caching cluster resources"""

    _instance: Optional["MonitoringRedisClient"] = None

    def __init__(self, settings: RedisSettings):
        self.url = settings.redis_url
        self._initialize()

    def __new__(cls, *args, **kwargs):
        """
        Factory method that creates either a SingleClusterK8sOperator or KarmadaK8sOperator
        based on the detected infrastructure.
        """
        # If we don't have an instance, set it (singleton)
        if cls._instance is None:
            cls._instance = super().__new__(MonitoringRedisClient)

        return cls._instance

    def _initialize(self):
        """Initialize Redis connection"""
        if not hasattr(self, "_redis"):
            try:
                self._redis = Redis.from_url(self.url, decode_responses=True)
                self._redis.ping()
                logger.info(f"Connected to Redis at {self.url}")
            except Exception as e:
                logger.error(f"Failed to connect to Redis: {e}")
                raise

    @property
    def redis(self) -> Redis:
        return self._redis

    def close(self):
        """Close Redis connection"""
        if self.redis:
            self.redis.close()

    async def track_cluster(self, cluster_name: str, resources: ClusterResources):
        await self.update_cluster_status(
            ClusterStatus(
                cluster_name=cluster_name,
                state=ClusterState.STARTING,
                last_heartbeat=datetime.now(timezone.utc),
            )
        )
        await self.store_initial_resources(cluster_name, resources)

    async def clear_cluster(self, cluster_name):
        try:
            await self.clear_cluster_resources(cluster_name)
            # Clear health data
            health_key = f"clusters:{cluster_name}:health"
            self.redis.delete(health_key)
        except Exception as e:
            logger.error(f"Failed to clear cluster {cluster_name}: {e}")
            raise

        # Pub/Sub methods
    def _publish_resource_change(self, cluster_name: str, event: WatchEvent):
        """Publish resource change event to Redis pub/sub"""
        try:
            # Create different channel types for different use cases
            channels = [
                f"cluster:{cluster_name}:resources",  # All resources for specific cluster
                f"cluster:{cluster_name}:resources:{event.resource_type}",  # Specific resource type for cluster
                f"resources:{event.resource_type}",  # All clusters for specific resource type
                "resources:all"  # All resource changes across all clusters
            ]
            
            # Create the message payload
            message = ResourceChangeMessage(
                cluster_name=cluster_name,
                event=event,
                timestamp=datetime.now(timezone.utc)
            )
            
            message_json = json.dumps(message.to_dict())
            
            # Publish to all relevant channels
            for channel in channels:
                self.redis.publish(channel, message_json)
                
            logger.debug(f"Published resource change to {len(channels)} channels: {event.resource_type} {event.obj_name}")
            
        except Exception as e:
            logger.error(f"Failed to publish resource change: {e}")
            # Don't raise - pub/sub failures shouldn't break the main functionality
    
    def subscribe_to_cluster_resources(self, cluster_name: str) -> PubSub:
        """Subscribe to all resource changes for a specific cluster"""
        pubsub = self.redis.pubsub()
        channel = f"cluster:{cluster_name}:resources"
        pubsub.subscribe(channel)
        logger.info(f"Subscribed to channel: {channel}")
        return pubsub
    
    def subscribe_to_resource_type(self, resource_type: str, cluster_name: Optional[str] = None) -> PubSub:
        """Subscribe to specific resource type changes"""
        pubsub = self.redis.pubsub()
        
        if cluster_name:
            channel = f"cluster:{cluster_name}:resources:{resource_type}"
        else:
            channel = f"resources:{resource_type}"
            
        pubsub.subscribe(channel)
        logger.info(f"Subscribed to channel: {channel}")
        return pubsub
    
    def subscribe_to_all_resources(self) -> PubSub:
        """Subscribe to all resource changes across all clusters"""
        pubsub = self.redis.pubsub()
        channel = "resources:all"
        pubsub.subscribe(channel)
        logger.info(f"Subscribed to channel: {channel}")
        return pubsub

    # Resource storage methods
    async def store_initial_resources(self, cluster_name: str, resources: ClusterResources):
        """Store initial resource dump for a cluster"""
        # Clear existing resources first
        await self.clear_cluster_resources(cluster_name)

        for resource_type, items in resources.items():
            if items:
                key = f"clusters:{cluster_name}:resources:{resource_type}"
                # Store each resource with its name as the hash field
                resource_map = {}
                for item in items:
                    resource_name = f"{item.metadata.namespace}:{item.metadata.name}"
                    _item = serializer.serialize(item)
                    resource_map[resource_name] = json.dumps(_item)

                if resource_map:
                    self.redis.hset(key, mapping=resource_map)

        logger.info(f"Stored initial resources for cluster {cluster_name}")

    async def update_resource(self, cluster_name: str, event: WatchEvent):
        """Update a single resource"""
        key = f"clusters:{cluster_name}:resources:{event.resource_type}"
        resource_name = f"{event.obj_namespace}:{event.obj_name}"

        if event.is_deleted:
            self.redis.hdel(key, resource_name)
        else:
            _item = serializer.serialize(event.object)
            self.redis.hset(key, resource_name, json.dumps(_item))

        # Publish the resource change event
        self._publish_resource_change(cluster_name, event)

    def get_resources(
        self, cluster_name: str = "*", resource_type: ResourceType = ResourceType.ALL, 
        resource_name: Optional[str] = None, namespace: Optional[str] = None
    ) -> ClusterResources:
        """Get resources for a cluster"""
        # Get all resource types
        pattern = f"clusters:{cluster_name}:resources:{resource_type.value}"
        keys = self.redis.keys(pattern)
        _results: dict[str, Any] = {}

        for key in keys:
            _resource_type = key.split(":")[-1]
            _resources = self.redis.hgetall(key)
            _resources = self._filter_resources(_resources, resource_name, namespace)
            # Initialize the resource type if it doesn't exist
            if _resource_type not in _results:
                _results[_resource_type] = {}
            
            # Merge the new resources with existing ones
            _results[_resource_type].update({k: json.loads(v) for k, v in _resources.items()})

        return ClusterResources.from_dict(_results)
    
    def _filter_resources(
        self, resources: dict[str, Any], resource_name: Optional[str] = None,
        namespace: Optional[str] = None
    ) -> dict[str, Any]:
        
        results = {}
        for k, v in resources.items():
            _parts = k.split(":")
            _resource_namespace = _parts[0]
            _resource_name = _parts[1]

            if resource_name and _resource_name != resource_name:
                continue

            if namespace and _resource_namespace != namespace:
                continue

            results[k] = v

        return results

    def get_resource_cluster(
            self, resource_name: str, resource_type: ResourceType, namespace: str = None
    ):
        pattern = f"clusters:*:resources:{resource_type.value}"
        keys = self.redis.keys(pattern)

        _clusters = []
        for key in keys:
            _cluster = key.split(":")[1]
            _cluster_resources = self.redis.hkeys(key)
            for resource_key in _cluster_resources:
                _parts = resource_key.split(":")
                _resource_namespace = _parts[0]
                _resource_name = _parts[1]
                if _resource_name == resource_name and _resource_namespace == namespace:
                    _clusters.append(_cluster)

        if len(_clusters) > 1:
            # logger.warning(f"Found multiple clusters with {resource_type.value} {resource_name} in namespace {namespace}, but execpted to only exist in 1 cluster.")
            raise ValueError(f"Found multiple clusters with {resource_type.value} {resource_name} in namespace {namespace}, but execpted to only exist in 1 cluster.")
        
        return _clusters[0] if len(_clusters) == 1 else None


    async def clear_cluster_resources(self, cluster_name: str):
        """Clear all resources for a cluster"""
        pattern = f"clusters:{cluster_name}:resources:*"
        keys = self.redis.keys(pattern)
        if keys:
            self.redis.delete(*keys)
            logger.info(f"Cleared {len(keys)} resource keys for cluster {cluster_name}")

    # Health tracking methods
    async def update_cluster_status(self, status: ClusterStatus):
        """Update cluster health status"""
        health_key = f"clusters:{status.cluster_name}:health"
        self.redis.hset(
            health_key,
            mapping={
                "cluster_name": status.cluster_name,
                "state": status.state.value,
                "last_heartbeat": status.last_heartbeat.isoformat()
                if status.last_heartbeat
                else "",
                "error_message": status.error_message or "",
                "heartbeat_failures": str(status.heartbeat_failures),
            },
        )

    async def increment_health_failures(self, cluster_name: str) -> int:
        """Increment health check failure count"""
        health_key = f"clusters:{cluster_name}:health"
        failures = self.redis.hincrby(health_key, "failures", 1)
        self.redis.expire(health_key, 300)
        return failures

    async def get_cluster_status(self, cluster_name: str) -> Optional[ClusterStatus]:
        """Get cluster health information"""
        health_key = f"clusters:{cluster_name}:health"
        health_data = self.redis.hgetall(health_key)
        cluster_status = None

        if health_data:
            cluster_status = ClusterStatus(
                cluster_name=health_data.get("cluster_name", cluster_name),
                state=ClusterState(health_data.get("state")),
                last_heartbeat=health_data.get("last_heartbeat") or None,
                error_message=health_data.get("error_message") or None,
                heartbeat_failures=int(health_data.get("heartbeat_failures", 0)),
            )

        return cluster_status

    async def get_all_cluster_statuses(self) -> List[ClusterStatus]:
        """Get all cluster health information"""
        # Option 1: Pipeline approach (most efficient)
        health_keys = self.redis.keys("clusters:*:health")
        cluster_statuses = []

        if health_keys:
            # Use pipeline to batch all hgetall calls
            pipeline = self.redis.pipeline()
            for health_key in health_keys:
                pipeline.hgetall(health_key)

            # Execute all commands at once
            results = pipeline.execute()

            for health_key, health_data in zip(health_keys, results):
                if health_data:
                    # Extract cluster name from the key
                    cluster_name = (
                        health_key.decode("utf-8").split(":")[1]
                        if isinstance(health_key, bytes)
                        else health_key.split(":")[1]
                    )

                    cluster_status = ClusterStatus(
                        cluster_name=health_data.get("cluster_name", cluster_name),
                        state=ClusterState(health_data.get("state")),
                        last_heartbeat=health_data.get("last_heartbeat") or None,
                        error_message=health_data.get("error_message") or None,
                        heartbeat_failures=int(health_data.get("heartbeat_failures", 0)),
                    )
                    cluster_statuses.append(cluster_status)

        return cluster_statuses

    # Utility methods
    def get_all_cluster_names(self) -> List[str]:
        """Get all registered cluster names"""
        pattern = "clusters:*:health"
        keys = self.redis.keys(pattern)
        return [key.split(":")[1] for key in keys]

    def get_resource_counts(self, cluster_name: str) -> Dict[str, int]:
        """Get resource counts for a cluster"""
        counts = {}
        for resource_type in ["deployments", "pods", "services"]:
            key = f"clusters:{cluster_name}:resources:{resource_type}"
            count = self.redis.hlen(key)
            counts[resource_type] = count
        return counts
