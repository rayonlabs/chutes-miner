# app/cache/redis_client.py
from datetime import datetime, timezone
from chutes_common.k8s import WatchEvent, serializer
from chutes_common.monitoring.models import ClusterResources, ClusterState, ClusterStatus
import json
from typing import Optional, Dict, Any, List
from loguru import logger
from chutes_monitor.config import settings
from redis import Redis

class MonitoringRedisClient:
    """Async Redis client for caching cluster resources"""
    
    _instance: Optional['MonitoringRedisClient'] = None
    
    def __init__(self):
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
        await self.update_cluster_status(ClusterStatus(
            cluster_name=cluster_name,
            state=ClusterState.STARTING,
            last_heartbeat=datetime.now(timezone.utc)
        ))
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
    
    async def get_cluster_resources(self, cluster_name: str, resource_type: Optional[str] = None) -> Dict[str, Any]:
        """Get resources for a cluster"""
        if resource_type:
            key = f"clusters:{cluster_name}:resources:{resource_type}"
            resources = self.redis.hgetall(key)
            return {k: json.loads(v) for k, v in resources.items()}
        else:
            # Get all resource types
            pattern = f"clusters:{cluster_name}:resources:*"
            keys = self.redis.keys(pattern)
            all_resources = {}
            
            for key in keys:
                resource_type = key.split(':')[-1]
                resources = self.redis.hgetall(key)
                all_resources[resource_type] = {k: json.loads(v) for k, v in resources.items()}
            
            return all_resources
    
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
        self.redis.hset(health_key, mapping={
            "cluster_name": status.cluster_name,
            "state": status.state.value,
            "last_heartbeat": status.last_heartbeat.isoformat() if status.last_heartbeat else "",
            "error_message": status.error_message or "",
            "heartbeat_failures": str(status.heartbeat_failures)
        })
    
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
                heartbeat_failures=int(health_data.get("heartbeat_failures", 0))
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
                    cluster_name = health_key.decode('utf-8').split(':')[1] if isinstance(health_key, bytes) else health_key.split(':')[1]
                    
                    cluster_status = ClusterStatus(
                        cluster_name=health_data.get("cluster_name", cluster_name),
                        state=ClusterState(health_data.get("state")),
                        last_heartbeat=health_data.get("last_heartbeat") or None,
                        error_message=health_data.get("error_message") or None,
                        heartbeat_failures=int(health_data.get("heartbeat_failures", 0))
                    )
                    cluster_statuses.append(cluster_status)
        
        return cluster_statuses
    
    # Utility methods
    async def get_all_cluster_names(self) -> List[str]:
        """Get all registered cluster names"""
        pattern = "clusters:*:health"
        keys = self.redis.keys(pattern)
        return [key.split(':')[1] for key in keys]
    
    async def get_resource_counts(self, cluster_name: str) -> Dict[str, int]:
        """Get resource counts for a cluster"""
        counts = {}
        for resource_type in ['deployments', 'pods', 'services']:
            key = f"clusters:{cluster_name}:resources:{resource_type}"
            count = self.redis.hlen(key)
            counts[resource_type] = count
        return counts