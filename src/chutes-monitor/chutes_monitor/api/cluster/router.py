# app/api/routes/clusters.py
from datetime import datetime, timezone
from chutes_common.auth import authorize
from chutes_common.constants import MONITORING_PURPOSE
from chutes_monitor.exceptions import ClusterConflictException, ClusterNotFoundException
from fastapi import APIRouter, Depends, HTTPException, status
from loguru import logger

from chutes_monitor.cluster_monitor import ClusterMonitor
from chutes_common.monitoring.models import ClusterState, ClusterStatus, HeartbeatData
from chutes_common.monitoring.requests import SetClusterResourcesRequest, ResourceUpdateRequest
from chutes_common.redis import MonitoringRedisClient


class ClusterRouter:
    def __init__(self):
        self.router = APIRouter()
        self._cluster_monitor = None
        self._redis_client = None
        self._setup_routes()

    @property
    def cluster_monitor(self):
        """Lazy initialization of cluster monitor"""
        if self._cluster_monitor is None:
            self._cluster_monitor = ClusterMonitor()
        return self._cluster_monitor

    @property
    def redis_client(self):
        """Lazy initialization of redis client"""
        if self._redis_client is None:
            self._redis_client = MonitoringRedisClient()
        return self._redis_client

    def _setup_routes(self):
        """Setup all the routes"""
        self.router.add_api_route("/{cluster_name}", self.register_cluster, methods=["POST"])
        self.router.add_api_route("/{cluster_name}", self.unregister_cluster, methods=["DELETE"])
        self.router.add_api_route(
            "/{cluster_name}/resources", self.set_cluster_resources, methods=["PUT"]
        )
        self.router.add_api_route(
            "/{cluster_name}/resources", self.update_resource, methods=["PATCH"]
        )
        self.router.add_api_route("/{cluster_name}/health", self.handle_heartbeat, methods=["PUT"])

    async def register_cluster(
        self, cluster_name: str, request: SetClusterResourcesRequest,
        _: None = Depends(authorize(allow_miner=True, purpose=MONITORING_PURPOSE)),
    ):
        """Register and start monitoring a new cluster"""
        try:
            await self.cluster_monitor.register_cluster(cluster_name, request.resources)
        except ClusterConflictException as e:
            logger.error(f"Failed to register cluster {cluster_name}:\n{e}")
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(e)
            )
        except Exception as e:
            logger.error(f"Error registering cluster {cluster_name}: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    async def unregister_cluster(
        self, cluster_name: str,
        _: None = Depends(authorize(allow_miner=True, purpose=MONITORING_PURPOSE)),
    ):
        """Unregister a cluster completely"""
        try:
            await self.cluster_monitor.delete_cluster(cluster_name)

            return {
                "message": f"Cluster {cluster_name} unregistered successfully",
                "cluster_name": cluster_name,
            }
        except Exception as e:
            logger.error(f"Error unregistering cluster {cluster_name}: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    async def set_cluster_resources(
            self, cluster_name: str, request: SetClusterResourcesRequest,
            _: None = Depends(authorize(allow_miner=True, purpose=MONITORING_PURPOSE)),
    ):
        """Register and start monitoring a new cluster"""
        try:
            await self.redis_client.update_cluster_status(
                ClusterStatus(
                    cluster_name=cluster_name,
                    state=ClusterState.STARTING,
                    last_heartbeat=datetime.now(timezone.utc),
                )
            )
            await self.cluster_monitor.set_cluster_resources(cluster_name, request.resources)
        except ClusterNotFoundException as e:
            logger.error(f"Failed to set resources for {cluster_name}:\n{e}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(e)
            )
        except Exception as e:
            logger.error(f"Error registering cluster {cluster_name}: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    async def update_resource(
            self, cluster_name: str, update: ResourceUpdateRequest,
            _: None = Depends(authorize(allow_miner=True, purpose=MONITORING_PURPOSE)),
    ):
        """Receive resource update from a member cluster"""
        try:
            await self.redis_client.update_resource(cluster_name, update.event)

            logger.debug(
                f"Updated {update.event.k8s_resource_type} for cluster {cluster_name}: {update.event.type}"
            )
            return {"status": "success", "cluster_name": cluster_name}

        except Exception as e:
            logger.error(f"Error updating resource for cluster {cluster_name}: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    async def handle_heartbeat(self, cluster_name: str, heartbeat: HeartbeatData):
        """Receive heartbeat from a member cluster"""
        try:
            logger.debug(f"Received heartbeat from cluster {cluster_name}")
            current_status = await self.redis_client.get_cluster_status(cluster_name)

            if not current_status:
                logger.debug(
                    f"Cluster {cluster_name} not in cache, rejecting heartbeat."
                )
                raise HTTPException(
                    status_code=404, detail="Cluster not in cache.  Resync resources."
                )

            if not current_status.is_healthy:
                logger.debug(
                    f"Cluster {cluster_name} is in an unhealthy state in cache, rejecting heartbeat."
                )
                raise HTTPException(
                    status_code=409, detail="Cluster is in an unhealthy state.  Resync resources."
                )

            await self.redis_client.update_cluster_status(
                ClusterStatus(
                    cluster_name=cluster_name,
                    state=heartbeat.state,
                    last_heartbeat=heartbeat.timestamp,
                )
            )
            return {"status": "success", "cluster_name": cluster_name}
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Error processing heartbeat for cluster {cluster_name}: {e}")
            raise HTTPException(status_code=500, detail=str(e))


# Create the router instance
cluster_router = ClusterRouter()
router = cluster_router.router
