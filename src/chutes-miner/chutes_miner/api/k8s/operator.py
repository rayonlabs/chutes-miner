import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from functools import lru_cache
import json
import math
import re
import time
import uuid
import traceback
import abc
import threading
from aiohttp import ConnectionTimeoutError
import semver
from chutes_common.monitoring.messages import (
    ClusterChangeMessage,
    ClusterReconnetMessage,
    ResourceChangeMessage,
)
from chutes_common.monitoring.models import ResourceType
from chutes_common.redis import MonitoringRedisClient
from chutes_miner.api.k8s.client import KubernetesMultiClusterClientManager
from chutes_miner.api.k8s.config import KubeConfig
from loguru import logger
from typing import Callable, Generator, List, Dict, Any, Optional, Tuple, Union
from kubernetes import watch
from kubernetes.client import (
    V1Deployment,
    V1Pod,
    V1Service,
    V1Node,
    V1NodeList,
    V1PodList,
    V1ObjectMeta,
    V1DeploymentList,
    V1ConfigMap,
    V1Job,
    V1JobList,
    V1ConfigMapList,
)
from kubernetes.client.rest import ApiException
from kubernetes.client import CoreV1Api
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from chutes_miner.api.exceptions import DeploymentFailure
from chutes_miner.api.database import get_session, get_sync_session
from chutes_miner.api.k8s.constants import (
    CHUTE_CODE_CM_PREFIX,
    CHUTE_DEPLOY_PREFIX,
    CHUTE_SVC_PREFIX,
    GRAVAL_JOB_PREFIX,
    GRAVAL_SVC_PREFIX,
)
from chutes_common.k8s import WatchEvent, WatchEventType
from chutes_miner.api.k8s.util import build_chute_job, build_chute_service
from chutes_common.schemas.server import Server
from chutes_common.schemas.chute import Chute
from chutes_common.schemas.deployment import Deployment
from chutes_common.schemas.gpu import GPU
from chutes_miner.api.config import (
    k8s_api_client,
    k8s_core_client,
    k8s_app_client,
    k8s_batch_client,
    settings,
)
from redis.client import PubSub
from urllib3.exceptions import MaxRetryError
import yaml

# Cache disk stats.
_disk_info_cache: dict[str, tuple[dict[str, float], datetime]] = {}
_disk_info_locks: dict[str, asyncio.Lock] = {}

# Cache TEE status per cluster/server name to avoid repeated DB lookups
# during bursts of rolling updates. TEE status is set once at server
# registration and never changes, so a long TTL is safe.
_tee_cluster_cache: dict[str, tuple[bool, datetime]] = {}
_TEE_CACHE_TTL = timedelta(minutes=10)


def _is_tee_cluster(cluster_name: str) -> bool:
    now = datetime.now(timezone.utc)
    cached = _tee_cluster_cache.get(cluster_name)
    if cached is not None:
        is_tee, expiry = cached
        if now < expiry:
            return is_tee

    with get_sync_session() as session:
        is_tee = session.execute(
            select(Server.is_tee).where(Server.name == cluster_name)
        ).scalar_one_or_none()
        result = is_tee is True

    _tee_cluster_cache[cluster_name] = (result, now + _TEE_CACHE_TTL)
    return result


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(slots=True)
class ConfigMapDeployRequest:
    config_map: V1ConfigMap
    namespace: str
    timeout_seconds: int = 60
    force: bool = False
    enqueued_at: datetime = field(default_factory=_utc_now)


@dataclass(slots=True)
class ConfigMapSyncRequest:
    cluster: str
    enqueued_at: datetime = field(default_factory=_utc_now)


ConfigMapWorkerRequest = Union[ConfigMapDeployRequest, ConfigMapSyncRequest]


class ConfigMapWorker:
    """Background worker that fan-outs ConfigMap updates across clusters."""

    _instance: Optional["ConfigMapWorker"] = None
    _instance_lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(
        self,
        *,
        redis_client: MonitoringRedisClient,
        manager: KubernetesMultiClusterClientManager,
        verify_node_health: Callable[[str], None],
        get_request_timeout: Callable[[int], Tuple[int, int]],
        build_code_config_map: Callable[[Chute], V1ConfigMap],
    ):
        if getattr(self, "_initialized", False):
            return

        self._redis = redis_client
        self._manager = manager
        self._verify_node_health = verify_node_health
        self._get_request_timeout = get_request_timeout
        self._build_code_config_map = build_code_config_map

        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._queue: Optional[asyncio.Queue[ConfigMapWorkerRequest]] = None
        self._thread: Optional[threading.Thread] = None
        self._worker_task: Optional[asyncio.Task] = None
        self._queue_ready = threading.Event()
        self._started = False
        self._start_lock = threading.Lock()

        self._initialized = True
        self._ensure_running()

    def _ensure_running(self):
        if self._started:
            return

        with self._start_lock:
            if self._started:
                return

            self._loop = asyncio.new_event_loop()
            self._queue_ready.clear()

            def _run_loop():
                asyncio.set_event_loop(self._loop)
                self._queue = asyncio.Queue()
                self._worker_task = self._loop.create_task(self._worker())
                self._queue_ready.set()
                try:
                    self._loop.run_forever()
                except Exception as exc:
                    logger.error(f"ConfigMapWorker loop encountered an error: {exc}")
                finally:
                    pending = asyncio.all_tasks()
                    for task in pending:
                        task.cancel()
                    if pending:
                        self._loop.run_until_complete(
                            asyncio.gather(*pending, return_exceptions=True)
                        )
                    self._loop.close()
                    self._started = False

            self._thread = threading.Thread(
                target=_run_loop,
                name="ChutesConfigMapWorker",
                daemon=True,
            )
            self._thread.start()

            if not self._queue_ready.wait(timeout=5):
                logger.error(
                    "Failed to start config map worker loop; falling back to synchronous deploys."
                )
                self._stop_loop()
                return

            self._started = True

    def _stop_loop(self):
        try:
            if self._loop:
                self._loop.call_soon_threadsafe(self._loop.stop)
        except Exception:
            pass
        self._loop = None
        self._queue = None
        self._worker_task = None
        self._thread = None
        self._started = False

    def enqueue_deploy(self, request: ConfigMapDeployRequest) -> bool:
        self._ensure_running()
        if not self._started:
            return False

        if not self._loop or not self._queue:
            logger.error("Config map worker loop unavailable after start; cannot submit request.")
            return False

        def _put_request():
            try:
                self._queue.put_nowait(request)
            except Exception as exc:
                logger.error(
                    f"Failed to enqueue configmap {request.config_map.metadata.name}: {exc}"
                )

        try:
            self._loop.call_soon_threadsafe(_put_request)
            return True
        except RuntimeError as exc:
            logger.error(
                f"Config map worker loop is not running; unable to enqueue {request.config_map.metadata.name}: {exc}"
            )
            return False

    def sync_cluster_configmaps(self, cluster: str) -> bool:
        self._ensure_running()
        if not self._started:
            return False

        if not self._loop or not self._queue:
            logger.error(
                "Config map worker loop unavailable after start; cannot enqueue sync request."
            )
            return False

        request = ConfigMapSyncRequest(cluster=cluster)

        def _put_request():
            try:
                self._queue.put_nowait(request)
            except Exception as exc:
                logger.error(f"Failed to enqueue configmap sync for cluster {cluster}: {exc}")

        try:
            self._loop.call_soon_threadsafe(_put_request)
            return True
        except RuntimeError as exc:
            logger.error(
                f"Config map worker loop is not running; unable to enqueue sync request for {cluster}: {exc}"
            )
            return False

    def process_deploy_sync(self, request: ConfigMapDeployRequest) -> Dict[str, str]:
        return self._handle_deploy_request(request)

    async def _worker(self):
        logger.info("Config map deployment worker loop started.")
        if not self._queue:
            logger.error("Config map worker queue not initialized; terminating worker loop.")
            return

        while True:
            try:
                request: ConfigMapWorkerRequest = await self._queue.get()
            except asyncio.CancelledError:
                break

            try:
                if isinstance(request, ConfigMapDeployRequest):
                    self._handle_deploy_request(request)
                elif isinstance(request, ConfigMapSyncRequest):
                    self._handle_sync_request(request)
                else:
                    logger.error(f"Unknown config map worker request type: {type(request)}")
            except Exception as exc:
                logger.error(
                    f"Unexpected error processing config map worker request {request}: {exc}"
                )
            finally:
                self._queue.task_done()

        logger.info("Config map deployment worker loop stopped.")

    def _handle_deploy_request(self, request: ConfigMapDeployRequest) -> Dict[str, str]:
        failures = self._deploy_config_map_to_all_clusters(
            config_map=request.config_map,
            namespace=request.namespace,
            timeout_seconds=request.timeout_seconds,
            force=request.force,
        )
        for cluster, reason in failures.items():
            logger.warning(
                f"Marking cluster {cluster} unhealthy after configmap {request.config_map.metadata.name} failure: {reason}"
            )
            self._redis.mark_cluster_unhealthy(cluster, reason)

        return failures

    def _handle_sync_request(self, request: ConfigMapSyncRequest) -> None:
        self._sync_cluster_configmaps(request.cluster)

    def _deploy_config_map_to_all_clusters(
        self,
        *,
        config_map: V1ConfigMap,
        namespace: str,
        timeout_seconds: int = 60,
        force: bool = False,
    ) -> Dict[str, str]:
        clusters = self._redis.get_all_cluster_names()
        failures: Dict[str, str] = {}
        for cluster in clusters:
            success, reason = self._deploy_config_map_to_cluster(
                cluster=cluster,
                config_map=config_map,
                namespace=namespace,
                timeout_seconds=timeout_seconds,
                force=force,
            )
            if not success:
                failures[cluster] = reason or "Unknown error"

        return failures

    def _deploy_config_map_to_cluster(
        self,
        *,
        cluster: str,
        config_map: V1ConfigMap,
        namespace: str,
        timeout_seconds: int = 60,
        force: bool = False,
    ) -> Tuple[bool, Optional[str]]:
        if _is_tee_cluster(cluster):
            return True, None
        cm_name = config_map.metadata.name
        client: Optional[CoreV1Api] = None
        try:
            self._verify_node_health(cluster)
            client = self._manager.get_core_client(cluster)
            if client is None:
                raise RuntimeError(f"No core client available for cluster {cluster}")

            client.create_namespaced_config_map(
                namespace=namespace,
                body=config_map,
                _request_timeout=self._get_request_timeout(timeout_seconds),
            )
            return True, None
        except (MaxRetryError, ConnectionTimeoutError) as exc:
            reason = f"Failed to deploy {cm_name} on cluster {cluster}, unable to connect: {exc}. CMs will reconcile on reconnect."
            logger.warning(reason)
            return False, reason
        except ApiException as e:
            if e.status == 409:
                if not force:
                    logger.debug(
                        f"Configmap {cm_name} already exists on cluster {cluster}; skipping because force=False."
                    )
                    return True, None

                logger.warning(f"Replacing configmap {cm_name} on cluster {cluster}.")
                try:
                    if client is None:
                        client = self._manager.get_core_client(cluster)
                    client.delete_namespaced_config_map(
                        name=cm_name,
                        namespace=namespace,
                        _request_timeout=self._get_request_timeout(timeout_seconds),
                    )
                    client.create_namespaced_config_map(
                        namespace=namespace,
                        body=config_map,
                        _request_timeout=self._get_request_timeout(timeout_seconds),
                    )
                    return True, None
                except ApiException as replace_exc:
                    reason = f"Failed to force replace configmap {cm_name} on cluster {cluster}: {replace_exc}"
                    logger.error(reason)
                    return False, reason
            elif e.status == 503:
                reason = f"Cluster {cluster} returned 503 when deploying configmap {cm_name}: {e}"
                logger.warning(reason)
                return False, reason
            else:
                reason = f"Failed to deploy configmap {cm_name} to cluster {cluster}: {e}"
                logger.error(reason)
                return False, reason
        except Exception as e:
            reason = f"Failed to deploy configmap {cm_name} to cluster {cluster}: {e}"
            logger.error(reason)
            return False, reason

    def _delete_config_map_from_cluster(
        self,
        *,
        cluster: str,
        name: str,
        namespace: str,
        timeout_seconds: int = 60,
    ) -> None:
        if _is_tee_cluster(cluster):
            return
        client = self._manager.get_core_client(cluster)
        try:
            client.delete_namespaced_config_map(
                name=name,
                namespace=namespace,
                _request_timeout=self._get_request_timeout(timeout_seconds),
            )
        except (MaxRetryError, ConnectionTimeoutError):
            # Cluster is unreachable, CMs will reconcile on reconnect
            logger.debug(
                f"Cluster {cluster} unreachable while deleting configmap {name}; will reconcile on reconnect."
            )
        except ApiException as e:
            if e.status != 404:
                raise

    def _sync_cluster_configmaps(self, cluster_name: str) -> None:
        if _is_tee_cluster(cluster_name):
            return
        try:
            with get_sync_session() as session:
                client = self._manager.get_core_client(cluster_name)
                chute_cms: V1ConfigMapList = client.list_namespaced_config_map(
                    settings.namespace, label_selector="chutes/code=true"
                )

                for cm in chute_cms.items:
                    self._delete_config_map_from_cluster(
                        cluster=cluster_name,
                        name=cm.metadata.name,
                        namespace=settings.namespace,
                    )

                chutes = (session.execute(select(Chute))).unique().scalars()
                for chute in chutes:
                    config_map = self._build_code_config_map(chute)
                    self._deploy_config_map_to_cluster(
                        cluster=cluster_name,
                        config_map=config_map,
                        namespace=settings.namespace,
                    )

            logger.info(f"Successfully synced chute configmaps for {cluster_name}")
        except Exception as e:
            logger.error(f"Unexpected exception syncing chute configmaps for {cluster_name}:\n{e}")


# Abstract base class for all Kubernetes operations
class K8sOperator(abc.ABC):
    """Base class for Kubernetes operations that works with both single-cluster and Karmada setups."""

    _instance: Optional["K8sOperator"] = None

    def __new__(cls, *args, **kwargs):
        """
        Factory method that creates either a SingleClusterK8sOperator or KarmadaK8sOperator
        based on the detected infrastructure.
        """
        # If we already have an instance, return it (singleton pattern)
        if cls._instance is not None:
            return cls._instance

        # If someone is trying to instantiate the concrete classes directly, let them
        if cls is not K8sOperator:
            instance = super().__new__(cls)
            return instance

        # Otherwise, determine which implementation to use
        try:
            # Detection logic
            nodes = k8s_core_client().list_node(
                label_selector="node.kubernetes.io/instance-type=k3s"
            )
            if nodes.items:
                logger.debug("Creating K8S Operator for Multi-Cluster")
                cls._instance = super().__new__(MultiClusterK8sOperator)
            else:
                logger.debug("Creating K8S Operator for Single Cluster")
                cls._instance = super().__new__(SingleClusterK8sOperator)
        except Exception:
            cls._instance = super().__new__(SingleClusterK8sOperator)

        return cls._instance

    def _extract_deployment_info(self, deployment: V1Deployment) -> Dict:
        """
        Extract deployment info from the deployment objects.
        """
        deploy_info = {
            "uuid": deployment.metadata.uid,
            "deployment_id": deployment.metadata.labels.get("chutes/deployment-id"),
            "name": deployment.metadata.name,
            "namespace": deployment.metadata.namespace,
            "labels": deployment.metadata.labels,
            "chute_id": deployment.metadata.labels.get("chutes/chute-id"),
            "version": deployment.metadata.labels.get("chutes/version"),
            "node_selector": deployment.spec.template.spec.node_selector,
        }
        deploy_info["ready"] = self._is_deployment_ready(deployment)
        pods = self.get_pods(
            namespace=deployment.metadata.namespace,
            label_selector=deployment.spec.selector.match_labels,
        )
        deploy_info["pods"] = []
        for pod in pods.items:
            state = (
                pod.status.container_statuses[0].state if pod.status.container_statuses else None
            )
            last_state = (
                pod.status.container_statuses[0].last_state
                if pod.status.container_statuses
                else None
            )
            pod_info = {
                "name": pod.metadata.name,
                "phase": pod.status.phase,
                "restart_count": pod.status.container_statuses[0].restart_count
                if pod.status.container_statuses
                else 0,
                "state": {
                    "running": state.running.to_dict() if state and state.running else None,
                    "terminated": state.terminated.to_dict()
                    if state and state.terminated
                    else None,
                    "waiting": state.waiting.to_dict() if state and state.waiting else None,
                }
                if state
                else None,
                "last_state": {
                    "running": last_state.running.to_dict()
                    if last_state and last_state.running
                    else None,
                    "terminated": last_state.terminated.to_dict()
                    if last_state and last_state.terminated
                    else None,
                    "waiting": last_state.waiting.to_dict()
                    if last_state and last_state.waiting
                    else None,
                }
                if last_state
                else None,
            }
            deploy_info["pods"].append(pod_info)
            deploy_info["node"] = pod.spec.node_name
        return deploy_info

    def is_job_ready(self, job):
        """
        Check if a job's pod is running and ready
        """
        # Get pods for this job
        pod_label_selector = (
            f"chutes/deployment-id={job.metadata.labels.get('chutes/deployment-id')}"
        )
        pods = self.get_pods(namespace=job.metadata.namespace, label_selector=pod_label_selector)

        for pod in pods.items:
            if pod.status.phase == "Running":
                # Check if all containers are ready
                if pod.status.container_statuses:
                    all_ready = all(cs.ready for cs in pod.status.container_statuses)
                    if all_ready:
                        return True
        return False

    def _extract_job_info(self, job: Any) -> Dict:
        """
        Extract job info from the job objects.
        """
        job_info = {
            "uuid": job.metadata.uid,
            "deployment_id": job.metadata.labels.get("chutes/deployment-id"),
            "name": job.metadata.name,
            "namespace": job.metadata.namespace,
            "labels": job.metadata.labels,
            "chute_id": job.metadata.labels.get("chutes/chute-id"),
            "version": job.metadata.labels.get("chutes/version"),
            "node_selector": job.spec.template.spec.node_selector,
            "node": job.spec.template.spec.node_name,
        }

        # Job status information
        job_info["ready"] = self.is_job_ready(job)
        job_info["status"] = {
            "active": job.status.active or 0,
            "succeeded": job.status.succeeded or 0,
            "failed": job.status.failed or 0,
            "completion_time": job.status.completion_time,
            "start_time": job.status.start_time,
        }

        pod_label_selector = (
            f"chutes/deployment-id={job.metadata.labels.get('chutes/deployment-id')}"
        )
        pods = self.get_pods(namespace=job.metadata.namespace, label_selector=pod_label_selector)
        job_info["pods"] = []
        for pod in pods.items:
            state = (
                pod.status.container_statuses[0].state if pod.status.container_statuses else None
            )
            last_state = (
                pod.status.container_statuses[0].last_state
                if pod.status.container_statuses
                else None
            )
            pod_info = {
                "name": pod.metadata.name,
                "phase": pod.status.phase,
                "restart_count": pod.status.container_statuses[0].restart_count
                if pod.status.container_statuses
                else 0,
                "state": {
                    "running": state.running.to_dict() if state and state.running else None,
                    "terminated": state.terminated.to_dict()
                    if state and state.terminated
                    else None,
                    "waiting": state.waiting.to_dict() if state and state.waiting else None,
                }
                if state
                else None,
                "last_state": {
                    "running": last_state.running.to_dict()
                    if last_state and last_state.running
                    else None,
                    "terminated": last_state.terminated.to_dict()
                    if last_state and last_state.terminated
                    else None,
                    "waiting": last_state.waiting.to_dict()
                    if last_state and last_state.waiting
                    else None,
                }
                if last_state
                else None,
            }
            job_info["pods"].append(pod_info)
        return job_info

    @abc.abstractmethod
    def watch_pods(
        self,
        namespace: Optional[str] = None,
        label_selector: Optional[Union[str | Dict[str, str]]] = None,
        field_selector: Optional[Union[str | Dict[str, str]]] = None,
        timeout=120,
    ) -> Generator[WatchEvent, None, None]:
        """
        Watch pods and yield events with type and pod object.

        Yields:
            dict: Event with 'type' ('ADDED', 'MODIFIED', 'DELETED') and 'object' (V1Pod)
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def get_pods(
        self,
        namespace: Optional[str] = None,
        label_selector: Optional[Union[str | Dict[str, str]]] = None,
        field_selector: Optional[Union[str | Dict[str, str]]] = None,
        timeout=120,
    ) -> V1PodList:
        """Get all Kubernetes nodes via k8s client, optionally filtering by GPU nodes."""
        raise NotImplementedError()

    async def get_kubernetes_nodes(self) -> List[Dict]:
        """
        Get all Kubernetes nodes via k8s client, optionally filtering by GPU nodes.
        """
        nodes = []
        try:
            node_list = self._get_nodes()
        except Exception as e:
            logger.error(f"Failed to get Kubernetes nodes: {e}")
            raise
        # Extract per-node so one malformed node (e.g. a node reporting no GPU capacity yet)
        # is skipped with a warning rather than taking down the whole reconcile loop.
        for node in node_list.items:
            try:
                node_info = await self._extract_node_info(node)
                nodes.append(node_info)
            except Exception as e:
                node_name = getattr(getattr(node, "metadata", None), "name", "unknown")
                logger.warning(f"Failed to extract node info for {node_name=}, skipping node: {e}")
        return nodes

    @abc.abstractmethod
    def get_node(self, name: str, kubeconfig: Optional[str] = None, timeout_seconds=15) -> V1Node:
        """
        Retrieve a node from the environment by name
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def _get_nodes(self) -> V1NodeList:
        """
        Retrieve all nodes from the environment
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def patch_node(self, name: str, body: Dict, timeout_seconds: int = 30) -> V1Node:
        raise NotImplementedError()

    async def _extract_node_info(self, node: V1Node):
        try:
            gpu_capacity = node.status.capacity.get("nvidia.com/gpu")
            if gpu_capacity is None or gpu_capacity == "0":
                logger.warning(f"Node has no GPU capacity: {node.metadata.name=}")
        except AttributeError:
            logger.warning(f"Node has invalid status or capacity: {node.metadata.name=}")

        gpu_count = int(node.status.capacity.get("nvidia.com/gpu", 0))
        gpu_mem_mb = int(node.metadata.labels.get("nvidia.com/gpu.memory", "32"))
        gpu_mem_gb = int(gpu_mem_mb / 1024)
        cpu_count = (
            int(node.status.capacity["cpu"]) - 2
        )  # leave 2 CPUs for incidentals, daemon sets, etc.
        if gpu_count > 0:
            cpus_per_gpu = (
                1 if cpu_count <= gpu_count else min(4, math.floor(cpu_count / gpu_count))
            )
        else:
            cpus_per_gpu = 0
        raw_mem = node.status.capacity["memory"]
        if raw_mem.endswith("Ki"):
            total_memory_gb = int(int(raw_mem.replace("Ki", "")) / 1024 / 1024) - 6
        elif raw_mem.endswith("Mi"):
            total_memory_gb = int(int(raw_mem.replace("Mi", "")) / 1024) - 6
        elif raw_mem.endswith("Gi"):
            total_memory_gb = int(raw_mem.replace("Gi", "")) - 6
        if gpu_count > 0:
            memory_gb_per_gpu = (
                1
                if total_memory_gb <= gpu_count
                else min(gpu_mem_gb, math.floor(total_memory_gb * 0.8 / gpu_count))
            )
        else:
            memory_gb_per_gpu = 0

        # Get disk space information
        disk_info = await self.get_node_disk_info(node.metadata.name)

        node_info = {
            "name": node.metadata.name,
            "validator": node.metadata.labels.get("chutes/validator"),
            "server_id": node.metadata.uid,
            "status": node.status.phase,
            "ip_address": node.metadata.labels.get("chutes/external-ip"),
            "cpu_per_gpu": cpus_per_gpu,
            "memory_gb_per_gpu": memory_gb_per_gpu,
            "disk_total_gb": disk_info.get("total_gb", 0),
            "disk_available_gb": disk_info.get("available_gb", 0),
            "disk_used_gb": disk_info.get("used_gb", 0),
        }
        return node_info

    @abc.abstractmethod
    async def get_deployment(self, deployment_id: str) -> Dict:
        """Get a single deployment by ID."""
        raise NotImplementedError()

    @abc.abstractmethod
    def _delete_deployment(
        self, name: str, namespace: str = settings.namespace, timeout_seconds: int = 120
    ):
        raise NotImplementedError()

    @abc.abstractmethod
    def get_deployments(
        self,
        namespace: Optional[str] = None,
        label_selector: Optional[Union[str | Dict[str, str]]] = None,
        field_selector: Optional[Union[str | Dict[str, str]]] = None,
        timeout=120,
    ) -> V1DeploymentList:
        """
        Get deployments, optinally filtering by namespace and labels
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def watch_deployments(
        self,
        namespace: Optional[str] = None,
        label_selector: Optional[Union[str | Dict[str, str]]] = None,
        field_selector: Optional[Union[str | Dict[str, str]]] = None,
        timeout=120,
    ) -> Generator[WatchEvent, None, None]:
        """
        Watch deployments and yield events with type and deployment object.

        Yields:
            dict: Event with 'type' ('ADDED', 'MODIFIED', 'DELETED') and 'object' (V1Deployment)
        """
        raise NotImplementedError()

    @abc.abstractmethod
    def get_jobs(
        self,
        namespace: Optional[str] = None,
        label_selector: Optional[Union[str | Dict[str, str]]] = None,
        field_selector: Optional[Union[str | Dict[str, str]]] = None,
        timeout=120,
    ) -> V1JobList:
        """
        Get jobs, optinally filtering by namespace and labels
        """
        raise NotImplementedError()

    def _is_deployment_ready(self, deployment):
        """
        Check if a deployment is "ready"
        """
        return (
            deployment.status.available_replicas is not None
            and deployment.status.available_replicas == deployment.spec.replicas
            and deployment.status.ready_replicas == deployment.spec.replicas
            and deployment.status.updated_replicas == deployment.spec.replicas
        )

    async def get_deployed_chutes(self) -> List[Dict]:
        """
        Get all chutes jobs from kubernetes.
        """
        jobs = []
        label_selector = "chutes/chute=true"
        job_list = self.get_jobs(namespace=settings.namespace, label_selector=label_selector)
        for job in job_list.items:
            jobs.append(self._extract_job_info(job))
            logger.info(
                f"Found chute job: {job.metadata.name} in namespace {job.metadata.namespace}"
            )
        return jobs

    async def _get_chute_deployments(self) -> List[Dict]:
        """
        Get all legacy chutes deployments (V1Deployment) from kubernetes.
        This is for backwards compatibility with the old deployment-based system.
        """
        deployments = []
        label_selector = "chutes/chute=true"
        try:
            deployment_list = self.get_deployments(
                namespace=settings.namespace, label_selector=label_selector
            )
            for deployment in deployment_list.items:
                deploy_info = {
                    "deployment_id": deployment.metadata.labels.get("chutes/deployment-id"),
                    "name": deployment.metadata.name,
                    "namespace": deployment.metadata.namespace,
                    "labels": deployment.metadata.labels,
                    "chute_id": deployment.metadata.labels.get("chutes/chute-id"),
                    "version": deployment.metadata.labels.get("chutes/version"),
                    "is_legacy": True,
                }
                deployments.append(deploy_info)
                logger.info(
                    f"Found legacy chute deployment: {deployment.metadata.name} in namespace {deployment.metadata.namespace}"
                )
        except Exception as e:
            logger.error(f"Failed to get legacy deployments: {e}")
        return deployments

    async def delete_code(self, chute_id: str, version: str) -> None:
        """
        Delete the code configmap associated with a chute & version.
        """
        try:
            code_uuid = self._get_code_uuid(chute_id, version)
            self.delete_config_map(f"{CHUTE_CODE_CM_PREFIX}-{code_uuid}")
        except ApiException as exc:
            if exc.status != 404:
                logger.error(f"Failed to delete code reference: {exc}")
                raise

    @abc.abstractmethod
    def delete_config_map(self, name: str, namespace=settings.namespace, timeout_seconds: int = 60):
        raise NotImplementedError()

    @lru_cache(maxsize=5)
    def _get_code_uuid(self, chute_id: str, version: str) -> str:
        return str(uuid.uuid5(uuid.NAMESPACE_OID, f"{chute_id}::{version}"))

    async def wait_for_deletion(self, label_selector: str, timeout_seconds: int = 120) -> None:
        """
        Wait for a deleted pod to be fully removed.
        Runs the blocking watch loop in a thread pool so the event loop is not blocked.
        """

        def _sync_wait() -> None:
            pods = self.get_pods(settings.namespace, label_selector, timeout=timeout_seconds)
            if not pods.items:
                logger.info(f"Nothing to wait for: {label_selector}")
                return
            try:
                for _ in self.watch_pods(
                    namespace=settings.namespace,
                    label_selector=label_selector,
                    timeout=timeout_seconds,
                ):
                    pods = self.get_pods(
                        settings.namespace, label_selector, timeout=timeout_seconds
                    )
                    if not pods.items:
                        logger.success(f"Deletion of {label_selector=} is complete")
                        break
            except Exception as exc:
                logger.warning(f"Error waiting for pods to be deleted: {exc}")
                raise

        await asyncio.to_thread(_sync_wait)

    async def undeploy(self, deployment_id: str, timeout_seconds: int | None = None) -> None:
        """
        Delete a job, and associated service.
        """
        wait_timeout = (
            timeout_seconds if timeout_seconds is not None else settings.chute_shutdown_time_seconds
        )

        node_name = None
        try:
            # TODO: This is problematic, if the job is deleted from k8s manually
            # cache doesn't return it and we get no node name, so cache can't be invalidated
            job = await self.get_deployment(deployment_id=deployment_id)
            node_name = job.get("node", None)
        except Exception:
            pass

        try:
            if node_name:
                self._delete_job(
                    name=f"{CHUTE_DEPLOY_PREFIX}-{deployment_id}", namespace=settings.namespace
                )
            else:
                # Handle fallback to cleaning up old deployments, from instances
                # Created before the 2025-07-17 upgrade.
                self._delete_deployment(
                    name=f"{CHUTE_DEPLOY_PREFIX}-{deployment_id}", namespace=settings.namespace
                )
        except Exception as exc:
            logger.warning(f"Error deleting deployment from k8s: {exc}")

        try:
            self._delete_service(f"{CHUTE_SVC_PREFIX}-{deployment_id}")
        except Exception as exc:
            logger.warning(
                f"Error removing primary service {CHUTE_SVC_PREFIX}-{deployment_id}: {exc}"
            )

        await self.wait_for_deletion(
            f"chutes/deployment-id={deployment_id}", timeout_seconds=wait_timeout
        )

        if node_name:
            self.invalidate_node_disk_cache(node_name)

    async def delete_preflight(self, deployment_id: str, timeout_seconds: int = 120) -> bool:
        """Hook for subclasses to veto undeploy when cache data is stale."""
        return True

    @abc.abstractmethod
    def _deploy_service(
        self,
        service: V1Service,
        server_name: Optional[str] = None,
        namespace=settings.namespace,
        timeout_seconds: int = 60,
    ):
        raise NotImplementedError()

    @abc.abstractmethod
    def _delete_service(self, name, namespace=settings.namespace, timeout_seconds: int = 60):
        raise NotImplementedError()

    @abc.abstractmethod
    def _deploy_job_for_deployment(
        self,
        job: V1Job,
        server_name: Optional[str] = None,
        namespace=settings.namespace,
        timeout_seconds=120,
    ):
        raise NotImplementedError()

    @abc.abstractmethod
    def _deploy_job(
        self,
        job: V1Job,
        server_name: Optional[str] = None,
        namespace=settings.namespace,
        timeout_seconds=120,
    ):
        raise NotImplementedError()

    @abc.abstractmethod
    def _delete_job(self, name, namespace=settings.namespace):
        raise NotImplementedError()

    async def create_code_config_map(self, chute: Chute, force=False) -> None:
        """Create a ConfigMap to store the chute code."""
        if chute.tee:
            return
        try:
            config_map = self._build_code_config_map(chute)
            await self._deploy_config_map(config_map, force=force)
        except ApiException as e:
            if e.status != 409:
                raise

    def _build_code_config_map(self, chute: Chute) -> V1ConfigMap:
        code_uuid = self._get_code_uuid(chute.chute_id, chute.version)
        config_map = V1ConfigMap(
            metadata=V1ObjectMeta(
                name=f"{CHUTE_CODE_CM_PREFIX}-{code_uuid}",
                labels={
                    "chutes/chute-id": chute.chute_id,
                    "chutes/version": chute.version,
                    "chutes/code": "true",
                },
            ),
            data={chute.filename: chute.code},
        )
        return config_map

    @abc.abstractmethod
    async def _deploy_config_map(
        self, config_map: V1ConfigMap, namespace=settings.namespace, timeout_seconds=60, force=False
    ):
        raise NotImplementedError()

    async def deploy_chute(
        self,
        chute_id: Union[str | Chute],
        server_id: Union[str | Server],
        token: str = None,
        job_id: str = None,
        config_id: str = None,
        disk_gb: int = 10,
        extra_labels: dict[str, str] = {},
        extra_service_ports: list[dict[str, Any]] = [],
        vm_version: Optional[str] = None,
    ) -> Tuple[Deployment, V1Job]:
        """Deploy a chute!"""
        try:
            # Backwards compatible types...
            if isinstance(chute_id, Chute):
                chute_id = chute_id.chute_id
            if isinstance(server_id, Server):
                server_id = server_id.server_id

            deployment_id = None
            chute_version = None
            async with get_session() as session:
                chute = await self._get_chute(session, chute_id)
                chute_version = chute.version
                server = await self._get_server(session, server_id)
                available_gpus = self._verify_gpus(chute, server)
                await self._verify_disk_space(server, disk_gb)
                deployment_id, gpu_uuids = await self._track_deployment(
                    session, chute, server, available_gpus, job_id, config_id
                )

            # Build the service that exposes it.
            service = self._create_service_for_deployment(
                chute, server, deployment_id, extra_service_ports
            )

            # Create the deployment.
            job = self._create_job_for_deployment(
                deployment_id,
                chute,
                server,
                service,
                gpu_uuids,
                token=token,
                job_id=job_id,
                config_id=config_id,
                disk_gb=disk_gb,
                vm_version=vm_version,
            )

            # Deploy the chute
            deployment = await self._update_deployment(deployment_id, server, service)

            self.invalidate_node_disk_cache(server.name)
            return deployment, job
        except Exception as exc:
            if deployment_id:
                await self._clear_deployment(deployment_id)

            try:
                if service:
                    self._delete_service(service.metadata.name)
            except Exception:
                ...

            try:
                if job:
                    self._delete_job(job.metadata.name)
            except Exception:
                ...

            logger.warning(
                f"Deployment of {chute_id=} on {server_id=} with {deployment_id=} {job_id=} failed, cleaning up service...: {exc=}"
            )

            raise DeploymentFailure(
                f"Failed to deploy chute {chute_id=} with version {chute_version}: {exc}\n{traceback.format_exc()}"
            )

    async def _get_chute(self, session: AsyncSession, chute_id: str):
        chute = (
            (await session.execute(select(Chute).where(Chute.chute_id == chute_id)))
            .unique()
            .scalar_one_or_none()
        )

        if not chute:
            raise DeploymentFailure(f"Failed to find chute: {chute_id=}")

        return chute

    async def _get_server(self, session: AsyncSession, server_id: str):
        server = (
            (await session.execute(select(Server).where(Server.server_id == server_id)))
            .unique()
            .scalar_one_or_none()
        )
        if not server:
            raise DeploymentFailure(f"Failed to find server: {server_id=}")

        return server

    def _verify_gpus(self, chute: Chute, server: Server):
        # Use the GPU's deployment_id FK directly rather than walking
        # Deployment.gpus relationships, which can be stale or incomplete
        # in async contexts with joined loading.
        available_gpus = {
            gpu.gpu_id for gpu in server.gpus if gpu.verified and gpu.deployment_id is None
        }
        gpus_allocated = sum(1 for gpu in server.gpus if gpu.deployment_id is not None)
        if len(available_gpus) < chute.gpu_count:
            raise DeploymentFailure(
                f"Server {server.server_id} name={server.name} cannot allocate {chute.gpu_count} GPUs, already using {gpus_allocated} of {len(server.gpus)}"
            )
        return available_gpus

    async def _track_deployment(
        self,
        session: AsyncSession,
        chute: Chute,
        server: Server,
        available_gpus,
        job_id: str = None,
        config_id: str = None,
    ):
        # Immediately track this deployment (before actually creating it) to avoid allocation contention.
        deployment_id = str(uuid.uuid4())
        gpu_candidates = [gpu for gpu in server.gpus if gpu.gpu_id in available_gpus][
            : chute.gpu_count
        ]
        gpu_ids = [gpu.gpu_id for gpu in gpu_candidates]
        gpu_uuids = [f"GPU-{str(uuid.UUID(gid))}" for gid in gpu_ids]
        logger.info(
            f"Assigning {len(gpu_uuids)} GPUs [{gpu_uuids}] to {chute.chute_id=} on {server.name=}"
        )
        deployment = Deployment(
            deployment_id=deployment_id,
            server_id=server.server_id,
            validator=server.validator,
            chute_id=chute.chute_id,
            version=chute.version,
            active=False,
            verified_at=None,
            stub=True,
            job_id=job_id,
            config_id=config_id,
            preemptible=chute.preemptible,
        )
        session.add(deployment)
        await session.flush()

        # Atomically claim only GPUs that are still unassigned.
        # The WHERE deployment_id IS NULL guard prevents stealing
        # GPUs that were concurrently assigned to another deployment.
        result = await session.execute(
            update(GPU)
            .where(
                GPU.gpu_id.in_(gpu_ids),
                GPU.deployment_id.is_(None),
            )
            .values(deployment_id=deployment_id)
        )
        claimed = result.rowcount
        if claimed < chute.gpu_count:
            raise DeploymentFailure(
                f"Could only claim {claimed}/{chute.gpu_count} GPUs on {server.name} "
                f"(contention with concurrent deployment)"
            )
        await session.commit()

        return deployment_id, gpu_uuids

    async def _clear_deployment(self, deployment_id: str):
        async with get_session() as session:
            deployment = (
                (
                    await session.execute(
                        select(Deployment).where(Deployment.deployment_id == deployment_id)
                    )
                )
                .unique()
                .scalar_one_or_none()
            )
            if deployment:
                await session.delete(deployment)
                await session.commit()

    async def _update_deployment(self, deployment_id: str, server: Server, service: V1Service):
        deployment_port = service.spec.ports[0].node_port
        async with get_session() as session:
            deployment = (
                (
                    await session.execute(
                        select(Deployment).where(Deployment.deployment_id == deployment_id)
                    )
                )
                .unique()
                .scalar_one_or_none()
            )
            if not deployment:
                raise DeploymentFailure("Deployment disappeared mid-flight!")
            deployment.host = server.ip_address
            deployment.port = deployment_port
            deployment.stub = False
            await session.commit()
            await session.refresh(deployment)

            return deployment

    async def _verify_disk_space(self, server: Server, disk_gb: int):
        # Check disk space availability
        if not await self.check_node_has_disk_available(server.name, disk_gb):
            raise DeploymentFailure(
                f"Server {server.server_id} name={server.name} does not have {disk_gb}GB disk space available"
            )

    def _get_probe_port(self, chute: Chute):
        # Determine the port to use for the liveness probe.
        probe_port = 8000
        core_version = re.match(
            r"^([0-9]+\.[0-9]+\.[0-9]+).*", (chute.chutes_version or "0.0.0")
        ).group(1)
        if semver.compare(core_version or "0.0.0", "0.3.3") >= 0:
            probe_port = 8001

        return probe_port

    async def deploy_graval(
        self, node: V1Node, job: V1Job, service: V1Service
    ) -> Tuple[V1Job, V1Service]:
        try:
            created_service = self._deploy_service(service, server_name=node.metadata.name)
            created_job = self._deploy_job(job, server_name=node.metadata.name)

            # Track the verification port.
            expected_port = created_service.spec.ports[0].node_port
            async with get_session() as session:
                result = await session.execute(
                    update(Server)
                    .where(Server.server_id == node.metadata.uid)
                    .values(verification_port=created_service.spec.ports[0].node_port)
                    .returning(Server.verification_port)
                )
                port = result.scalar_one_or_none()
                if port != expected_port:
                    raise DeploymentFailure(
                        f"Unable to track verification port for newly added node: {expected_port=} actual_{port=}"
                    )
                await session.commit()
            return created_job, created_service
        except ApiException as exc:
            try:
                self._delete_service(name=service.metadata.name)
            except Exception:
                ...
            try:
                self._delete_job(name=job.metadata.name)
            except Exception:
                ...
            raise DeploymentFailure(
                f"Failed to deploy GraVal: {str(exc)}:\n{traceback.format_exc()}"
            )

    async def cleanup_graval(self, node: V1Node):
        node_name = node.metadata.name
        nice_name = node_name.replace(".", "-")
        try:
            self._delete_service(f"{GRAVAL_SVC_PREFIX}-{nice_name}")
        except Exception:
            ...

        try:
            self._delete_job(f"{GRAVAL_JOB_PREFIX}-{nice_name}")
            label_selector = f"graval-node={nice_name}"

            await self.wait_for_deletion(label_selector)
        except Exception:
            ...

    def invalidate_node_disk_cache(self, node_name: str):
        """
        Invalidate the disk cache for a specific node.
        """
        if node_name in _disk_info_cache:
            logger.info(f"Invalidating cached disk size check for {node_name=}")
            del _disk_info_cache[node_name]

    async def get_node_disk_info(self, node_name: str) -> Dict[str, float]:
        """
        Get disk space information for a specific node with caching.
        Returns dict with total_gb, available_gb, used_gb
        """
        # Check cache first
        if node_name in _disk_info_cache:
            disk_info, expiry_time = _disk_info_cache[node_name]
            if datetime.now() < expiry_time:
                return disk_info

        # Get or create a lock for this node
        if node_name not in _disk_info_locks:
            _disk_info_locks[node_name] = asyncio.Lock()

        async with _disk_info_locks[node_name]:
            if node_name in _disk_info_cache:
                disk_info, expiry_time = _disk_info_cache[node_name]
                if datetime.now() < expiry_time:
                    return disk_info

            logger.info(f"Fetching fresh disk info for node {node_name}")
            try:
                pods = self.get_pods(field_selector=f"spec.nodeName={node_name}")
                used_disk_gb = 0
                for pod in pods.items:
                    if pod.status.phase not in ["Running", "Pending"]:
                        continue

                    # Check containers for ephemeral-storage requests
                    if pod.spec.containers:
                        for container in pod.spec.containers:
                            if container.resources and container.resources.requests:
                                ephemeral_storage = container.resources.requests.get(
                                    "ephemeral-storage", "0"
                                )
                                if isinstance(ephemeral_storage, str):
                                    if ephemeral_storage.endswith("Gi"):
                                        used_disk_gb += float(ephemeral_storage.replace("Gi", ""))
                                    elif ephemeral_storage.endswith("G"):
                                        used_disk_gb += float(ephemeral_storage.replace("G", ""))
                                    elif ephemeral_storage.endswith("Mi"):
                                        used_disk_gb += (
                                            float(ephemeral_storage.replace("Mi", "")) / 1024
                                        )
                                    elif ephemeral_storage.endswith("M"):
                                        used_disk_gb += (
                                            float(ephemeral_storage.replace("M", "")) / 1024
                                        )
                                    elif ephemeral_storage.endswith("Ki"):
                                        used_disk_gb += (
                                            float(ephemeral_storage.replace("Ki", "")) / 1024 / 1024
                                        )

                    # Also check init containers
                    if pod.spec.init_containers:
                        for container in pod.spec.init_containers:
                            if container.resources and container.resources.requests:
                                ephemeral_storage = container.resources.requests.get(
                                    "ephemeral-storage", "0"
                                )
                                if isinstance(ephemeral_storage, str):
                                    if ephemeral_storage.endswith("Gi"):
                                        used_disk_gb += float(ephemeral_storage.replace("Gi", ""))
                                    elif ephemeral_storage.endswith("G"):
                                        used_disk_gb += float(ephemeral_storage.replace("G", ""))
                                    elif ephemeral_storage.endswith("Mi"):
                                        used_disk_gb += (
                                            float(ephemeral_storage.replace("Mi", "")) / 1024
                                        )
                                    elif ephemeral_storage.endswith("M"):
                                        used_disk_gb += (
                                            float(ephemeral_storage.replace("M", "")) / 1024
                                        )
                                    elif ephemeral_storage.endswith("Ki"):
                                        used_disk_gb += (
                                            float(ephemeral_storage.replace("Ki", "")) / 1024 / 1024
                                        )

                # Get node capacity
                node = self.get_node(name=node_name)

                # Try to get ephemeral storage capacity
                ephemeral_storage = node.status.capacity.get("ephemeral-storage", "0")
                if ephemeral_storage.endswith("Ki"):
                    total_disk_gb = int(ephemeral_storage.replace("Ki", "")) / 1024 / 1024
                elif ephemeral_storage.endswith("Mi"):
                    total_disk_gb = int(ephemeral_storage.replace("Mi", "")) / 1024
                elif ephemeral_storage.endswith("Gi"):
                    total_disk_gb = int(ephemeral_storage.replace("Gi", ""))
                else:
                    logger.warning(
                        "Could not determine node ephemeral storage capacity, using default=100"
                    )
                    total_disk_gb = 100

                # Reserve some disk space for system operations
                system_reserved_gb = 20
                available_disk_gb = total_disk_gb - used_disk_gb - system_reserved_gb
                disk_info = {
                    "total_gb": total_disk_gb,
                    "available_gb": max(0, available_disk_gb),
                    "used_gb": used_disk_gb,
                }

                # Cache the result with 5 minute expiry
                expiry_time = datetime.now() + timedelta(minutes=5)
                _disk_info_cache[node_name] = (disk_info, expiry_time)
                logger.info(
                    f"Node {node_name} disk info: total={total_disk_gb}GB, used={used_disk_gb}GB, available={available_disk_gb}GB"
                )
                return disk_info

            except Exception as e:
                logger.warning(f"Failed to get disk info for node {node_name}: {e}")
                error_result = {
                    "total_gb": 0,
                    "available_gb": 0,
                    "used_gb": 0,
                }
                expiry_time = datetime.now() + timedelta(minutes=1)
                _disk_info_cache[node_name] = (error_result, expiry_time)

                return error_result

    async def check_node_has_disk_available(self, node_name: str, required_disk_gb: int) -> bool:
        """
        Check if a node has sufficient disk space available for a deployment.
        """
        disk_info = await self.get_node_disk_info(node_name)
        return disk_info.get("available_gb", 0) >= required_disk_gb

    def _create_service_for_deployment(
        self,
        chute: Chute,
        server: Server,
        deployment_id: str,
        extra_service_ports: list[dict[str, Any]] = [],
    ):
        service = build_chute_service(chute, deployment_id, extra_service_ports)

        try:
            created_service = self._deploy_service(service, server_name=server.name)
        except Exception:
            raise DeploymentFailure(
                f"Failed to create service for {chute.chute_id=} and {deployment_id=}"
            )

        return created_service

    def _create_job_for_deployment(
        self,
        deployment_id,
        chute: Chute,
        server: Server,
        service: V1Service,
        gpu_uuids: list[str],
        token: Optional[str] = None,
        job_id: Optional[str] = None,
        config_id: Optional[str] = None,
        disk_gb: int = 10,
        vm_version: Optional[str] = None,
    ) -> V1Job:
        probe_port = self._get_probe_port(chute)
        job = build_chute_job(
            deployment_id,
            chute,
            server,
            service,
            gpu_uuids,
            probe_port,
            token=token,
            job_id=job_id,
            config_id=config_id,
            disk_gb=disk_gb,
            vm_version=vm_version,
        )

        try:
            created_job = self._deploy_job_for_deployment(job, server_name=server.name)
        except Exception:
            raise DeploymentFailure(
                f"Failed to create job for {chute.chute_id=} and {deployment_id=}"
            )

        return created_job


# Legacy single-cluster implementation
class SingleClusterK8sOperator(K8sOperator):
    """Kubernetes operations for legacy single-cluster setup."""

    def get_node(self, name: str, kubeconfig: Optional[str] = None, timeout_seconds=15) -> V1Node:
        """
        Retrieve all nodes from the environment
        """
        if kubeconfig:
            raise RuntimeError(
                "Can not retrieve node using kubeconfig in single cluster environment. Do not provide an IP address when adding a node."
            )
        return k8s_core_client().read_node(name=name, _request_timeout=timeout_seconds)

    def _get_nodes(self):
        """
        Retrieve all nodes from the environment
        """
        node_list = k8s_core_client().list_node(field_selector=None, label_selector="chutes/worker")
        return node_list

    def patch_node(self, name, body, timeout_seconds: int = 30):
        return k8s_core_client().patch_node(name=name, body=body, _request_timeout=timeout_seconds)

    def watch_pods(self, namespace=None, label_selector=None, field_selector=None, timeout=120):
        if label_selector:
            label_selector = (
                label_selector
                if isinstance(label_selector, str)
                else ",".join(f"{k}={v}" for k, v in label_selector.items())
            )

        if field_selector:
            field_selector = (
                field_selector
                if isinstance(field_selector, str)
                else ",".join(f"{k}={v}" for k, v in field_selector.items())
            )

        # Use the standard Kubernetes watch mechanism
        w = watch.Watch()
        try:
            for event in w.stream(
                k8s_core_client().list_namespaced_pod,
                namespace=namespace,
                label_selector=label_selector,
                field_selector=field_selector,
                timeout_seconds=timeout,
            ):
                # Need to pass in object as dict to avoid pydantic errors
                # Since watch event expects objects from k8s_asyncio
                yield WatchEvent.from_dict(
                    {
                        "type": event["type"],
                        "object": k8s_api_client().sanitize_for_serialization(event["object"]),
                    }
                )
        finally:
            w.stop()

    def get_pods(
        self,
        namespace: Optional[str] = None,
        label_selector: Optional[Union[str | Dict[str, str]]] = None,
        field_selector: Optional[Union[str | Dict[str, str]]] = None,
        timeout=120,
    ) -> V1PodList:
        if label_selector:
            label_selector = (
                label_selector
                if isinstance(label_selector, str)
                else ",".join([f"{k}={v}" for k, v in label_selector.items()])
            )

        if field_selector:
            field_selector = (
                field_selector
                if isinstance(field_selector, str)
                else ",".join([f"{k}={v}" for k, v in field_selector.items()])
            )

        if namespace:
            pods = k8s_core_client().list_namespaced_pod(
                namespace=namespace,
                label_selector=label_selector,
                field_selector=field_selector,
                timeout_seconds=timeout,
            )
        else:
            pods = k8s_core_client().list_pod_for_all_namespaces(
                label_selector=label_selector,
                field_selector=field_selector,
                timeout_seconds=timeout,
            )

        return pods

    async def get_deployment(self, deployment_id: str) -> Dict:
        """
        Get a single deployment by ID.
        """
        job = k8s_batch_client().read_namespaced_job(
            namespace=settings.namespace,
            name=f"{CHUTE_DEPLOY_PREFIX}-{deployment_id}",
        )
        return self._extract_job_info(job)

    def get_deployments(
        self,
        namespace: Optional[str] = settings.namespace,
        label_selector: Optional[Union[str | Dict[str, str]]] = None,
        field_selector: Optional[Union[str | Dict[str, str]]] = None,
        timeout=120,
    ) -> V1DeploymentList:
        """
        Get deployment, optinally filtering by namespace and labels
        """
        if label_selector:
            label_selector = (
                label_selector
                if isinstance(label_selector, str)
                else ",".join(f"{k}={v}" for k, v in label_selector.items())
            )

        if field_selector:
            field_selector = (
                field_selector
                if isinstance(field_selector, str)
                else ",".join(f"{k}={v}" for k, v in field_selector.items())
            )

        deployment_list = k8s_app_client().list_namespaced_deployment(
            namespace=namespace,
            label_selector=label_selector,
            field_selector=field_selector,
            timeout_seconds=timeout,
        )

        return deployment_list

    def watch_deployments(
        self,
        namespace: Optional[str] = None,
        label_selector: Optional[Union[str | Dict[str, str]]] = None,
        field_selector: Optional[Union[str | Dict[str, str]]] = None,
        timeout=120,
    ):
        """Watch deployments using standard Kubernetes watch API."""
        if label_selector:
            label_selector = (
                label_selector
                if isinstance(label_selector, str)
                else ",".join(f"{k}={v}" for k, v in label_selector.items())
            )

        if field_selector:
            field_selector = (
                field_selector
                if isinstance(field_selector, str)
                else ",".join(f"{k}={v}" for k, v in field_selector.items())
            )

        # Use the standard Kubernetes watch mechanism
        w = watch.Watch()
        try:
            for event in w.stream(
                k8s_app_client().list_namespaced_deployment,
                namespace=namespace,
                label_selector=label_selector,
                field_selector=field_selector,
                timeout_seconds=timeout,
            ):
                # Need to pass in object as dict to avoid pydantic errors
                # Since watch event expects objects from k8s_asyncio
                yield WatchEvent.from_dict(
                    {
                        "type": event["type"],
                        "object": k8s_api_client().sanitize_for_serialization(event["object"]),
                    }
                )
        finally:
            w.close()

    def _delete_deployment(self, name, namespace=settings.namespace, timeout_seconds: int = 120):
        k8s_app_client().delete_namespaced_deployment(
            name=name, namespace=namespace, _request_timeout=timeout_seconds
        )

    def get_jobs(
        self,
        namespace: Optional[str] = settings.namespace,
        label_selector: Optional[Union[str | Dict[str, str]]] = None,
        field_selector: Optional[Union[str | Dict[str, str]]] = None,
        timeout=120,
    ) -> V1JobList:
        if label_selector:
            label_selector = (
                label_selector
                if isinstance(label_selector, str)
                else ",".join(f"{k}={v}" for k, v in label_selector.items())
            )

        if field_selector:
            field_selector = (
                field_selector
                if isinstance(field_selector, str)
                else ",".join(f"{k}={v}" for k, v in field_selector.items())
            )

        jobs_list = k8s_batch_client().list_namespaced_job(
            namespace=namespace,
            label_selector=label_selector,
            field_selector=field_selector,
            timeout_seconds=timeout,
        )

        return jobs_list

    def _deploy_service(
        self, service, server_name=None, namespace=settings.namespace, timeout_seconds: int = 60
    ):
        return k8s_core_client().create_namespaced_service(
            namespace=namespace, body=service, _request_timeout=timeout_seconds
        )

    def _delete_service(self, name, namespace=settings.namespace, timeout_seconds: int = 60):
        k8s_core_client().delete_namespaced_service(
            name=name, namespace=namespace, _request_timeout=timeout_seconds
        )

    def _deploy_job_for_deployment(
        self,
        job: V1Job,
        server_name: Optional[str] = None,
        namespace=settings.namespace,
        timeout_seconds=120,
    ):
        return self._deploy_job(job, server_name, namespace, timeout_seconds=timeout_seconds)

    def _deploy_job(self, job, server_name=None, namespace=settings.namespace, timeout_seconds=120):
        return k8s_batch_client().create_namespaced_job(
            namespace=namespace, body=job, _request_timeout=timeout_seconds
        )

    def _delete_job(self, name, namespace=settings.namespace):
        k8s_batch_client().delete_namespaced_job(
            name=name,
            namespace=namespace,
            propagation_policy="Foreground",
            grace_period_seconds=settings.chute_shutdown_time_seconds,
        )

    def delete_config_map(self, name, namespace=settings.namespace, timeout_seconds: int = 60):
        k8s_core_client().delete_namespaced_config_map(
            name=name, namespace=namespace, _request_timeout=timeout_seconds
        )

    async def _deploy_config_map(
        self, config_map: V1ConfigMap, namespace=settings.namespace, timeout_seconds=60, force=False
    ):
        try:
            k8s_core_client().create_namespaced_config_map(
                namespace=namespace, body=config_map, _request_timeout=timeout_seconds
            )
        except ApiException as e:
            if e.status == 409:
                if force:
                    k8s_core_client().delete_namespaced_config_map(
                        name=config_map.metadata.name,
                        namespace=namespace,
                        _request_timeout=timeout_seconds,
                    )
                    k8s_core_client().create_namespaced_config_map(
                        namespace=namespace, body=config_map, _request_timeout=timeout_seconds
                    )
            else:
                raise


class MultiClusterK8sOperator(K8sOperator):
    """Kubernetes operations for multi-cluster setup."""

    # This class will implement the K8sOperator interface but translate operations
    # to work with k3s multi-cluster orchestration
    def __init__(self):
        self._config_map_worker: Optional[ConfigMapWorker] = None
        self._initialize()

    def _initialize(self):
        # Ugly pattern to ensure we don't kick this off every time singleton is called.
        if not hasattr(self, "_cluster_monitor_task"):
            self._cluster_monitor_task = asyncio.create_task(self._watch_clusters())

        if not hasattr(self, "_manager"):
            self._manager = KubernetesMultiClusterClientManager()

        if not hasattr(self, "_redis"):
            self._redis = MonitoringRedisClient()

        if settings.reconcile_clusters:
            if not hasattr(self, "_watch_reconnects_task"):
                self.watch_cluster_connections()

            if not self._config_map_worker:
                self._config_map_worker = ConfigMapWorker(
                    redis_client=self._redis,
                    manager=self._manager,
                    verify_node_health=self._verify_node_health,
                    get_request_timeout=self._get_request_timeout,
                    build_code_config_map=self._build_code_config_map,
                )

    def _get_request_timeout(self, read_timeout: int) -> Tuple[int, int]:
        return (5, read_timeout)

    async def delete_preflight(self, deployment_id: str, timeout_seconds: int = 120) -> bool:
        deployment_name = f"{CHUTE_DEPLOY_PREFIX}-{deployment_id}"
        should_allow_delete = True

        server_name = await self._get_deployment_server(deployment_id)
        context: Optional[str] = None
        cached_job = None

        if not server_name:
            logger.info(
                f"Preflight delete for {deployment_name} allowed: deployment not found in DB, assuming orphaned deployment."
            )
            return True
        else:
            context, cached_job = self._redis.get_resource_with_context(
                resource_type=ResourceType.JOB,
                resource_name=deployment_name,
                namespace=settings.namespace,
            )

            if context and context != server_name:
                logger.error(
                    f"Preflight delete for {deployment_name} blocked: cache context {context} does not match DB server {server_name}."
                )
                should_allow_delete = False
            elif not self._cluster_is_healthy(server_name):
                logger.warning(
                    f"Preflight delete for {deployment_name} blocked: cluster {server_name} unhealthy or offline."
                )
                should_allow_delete = False
            elif cached_job and self._is_resource_stale(
                cluster=server_name,
                cached_resource=cached_job,
                read_live_resource=self._read_live_job,
                timeout_seconds=timeout_seconds,
            ):
                logger.warning(
                    f"Preflight delete for {deployment_name} on cluster {server_name} failed due to cache mismatch."
                )
                should_allow_delete = False
            elif not context or not cached_job:
                logger.debug(
                    f"Preflight bypassed for {deployment_name}: resource not found in cache but server {server_name} is healthy."
                )

        return should_allow_delete

    async def _get_deployment_server(self, deployment_id: str) -> Optional[str]:
        async with get_session() as session:
            query = (
                select(Server.name)
                .select_from(Deployment)
                .join(Server, Deployment.server_id == Server.server_id, isouter=True)
                .where(Deployment.deployment_id == deployment_id)
            )

            result = await session.execute(query)
            return result.scalar_one_or_none()

    def _cluster_is_healthy(self, cluster: str) -> bool:
        status = self._redis.get_cluster_status(cluster)
        if not status or not status.is_healthy:
            logger.warning(
                f"Cluster {cluster} health status is {'unknown' if not status else status.state}, treating as unhealthy."
            )
            return False

        return True

    async def _watch_clusters(self):
        try:
            pubsub = self._redis.subscribe_to_clusters()

            while True:
                try:
                    message = pubsub.get_message(timeout=1)
                    if message and message["type"] == "message":
                        data = json.loads(message["data"])
                        _message = ClusterChangeMessage.from_dict(data)
                        await self._handle_cluster_change(_message)
                    else:
                        await asyncio.sleep(1)

                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"Unexpected error while watching clusters:\n{e}")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Unexpected error while watching clusters:\n{e}")
        finally:
            pubsub.close()

    async def _handle_cluster_change(self, message: ClusterChangeMessage):
        try:
            if message.event_type == WatchEventType.DELETED:
                self._manager.multi_config.remove_config(message.cluster)
            elif message.event_type == WatchEventType.ADDED:
                async with get_session() as session:
                    server = (
                        (
                            await session.execute(
                                select(Server).where(Server.name == message.cluster)
                            )
                        )
                        .unique()
                        .scalar_one_or_none()
                    )

                    if server:
                        if server.kubeconfig:
                            self._manager.multi_config.add_config(
                                KubeConfig.from_dict(yaml.safe_load(server.kubeconfig))
                            )

                            if (
                                settings.reconcile_clusters
                                and self._config_map_worker
                                and not self._config_map_worker.sync_cluster_configmaps(
                                    message.cluster
                                )
                            ):
                                logger.error(
                                    f"Failed to enqueue configmap sync for cluster {message.cluster}."
                                )
                        else:
                            logger.warning(
                                f"Received add event for cluster {message.cluster} but no kubeconfig is set in DB."
                            )
                    else:
                        logger.warning(
                            f"Received add event for cluster {message.cluster}, but does not exist in DB"
                        )
        except Exception as e:
            logger.error(f"Unexpected exception while handling cluster change:\n{e}")

    def watch_cluster_connections(self):
        """
        Reconcile chutes on a regular basis.
        """
        try:
            self._watch_reconnects_task = asyncio.create_task(self._watch_cluster_connections())
        except Exception as e:
            logger.error(
                f"Unexpected error watching cluster connections: {e}\n{traceback.format_exc()}"
            )

    async def _watch_cluster_connections(self):
        try:
            pubsub = self._redis.subscribe_to_cluster_reconnect()

            while True:
                try:
                    message = pubsub.get_message(timeout=1)
                    if message and message["type"] == "message":
                        data = json.loads(message["data"])
                        _message = ClusterReconnetMessage.from_dict(data)
                        await self._handle_cluster_reconnect(_message)
                    else:
                        await asyncio.sleep(15)

                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"Unexpected error getting cluster reconnects messages:\n{e}")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Unexpected error while watching cluster reconnects:\n{e}")
        finally:
            pubsub.close()

    async def _handle_cluster_reconnect(self, message: ClusterReconnetMessage):
        try:
            if not settings.reconcile_clusters:
                return

            if not self._config_map_worker:
                logger.warning(
                    f"Cluster {message.cluster} reconnected but config map worker is unavailable; skipping sync."
                )
                return

            logger.info(f"Cluster {message.cluster} reconnected.  Refreshing Chutes config maps.")

            if not self._config_map_worker.sync_cluster_configmaps(message.cluster):
                logger.error(
                    f"Failed to enqueue configmap sync for cluster {message.cluster} after reconnect."
                )

        except Exception as e:
            logger.error(f"Unexpected exception while handling cluster change:\n{e}")

    def get_node(
        self, name: str, kubeconfig: Optional[KubeConfig] = None, timeout_seconds=15
    ) -> V1Node:
        """
        Retrieve a node from the cluster by name.
        """
        try:
            # If kubeconfig provided this is the initial node retrieval, can't verify health
            if not kubeconfig:
                # If the server isn't healthy don't return the node from cache
                self._verify_node_health(name)

            _client: CoreV1Api = self._manager.get_core_client(
                context_name=name, kubeconfig=kubeconfig
            )

            return _client.read_node(
                name=name, _request_timeout=self._get_request_timeout(timeout_seconds)
            )
        except ApiException:
            raise
        except Exception as e:
            logger.error(f"Failed to get node:\n{e}")
            raise ApiException(status=503, reason=f"Unexpected error getting node {name}:\n{e}")

    def _get_nodes(self) -> V1NodeList:
        resources = self._redis.get_resources(resource_type=ResourceType.NODE)
        return V1NodeList(items=resources.nodes)

    def patch_node(self, name: str, body: Dict, timeout_seconds: int = 30) -> V1Node:
        # cluster = self._redis.get_resource_cluster(resource_name=name, resource_type="node")
        # We can assume the node name is the same as the context, if this changes this will break
        client = self._manager.get_core_client(context_name=name)
        client.patch_node(
            name=name, body=body, _request_timeout=self._get_request_timeout(timeout_seconds)
        )

        return self.get_node(name)

    def _verify_node_health(self, name: str):
        status = self._redis.get_cluster_status(name)
        if status and not status.is_healthy:
            raise ApiException(status=503, reason=f"Node {name} is not healthy, check the agent.")

    def _read_live_deployment(
        self, cluster: str, namespace: Optional[str], name: str, timeout_seconds: int
    ):
        client = self._manager.get_app_client(cluster)
        if client is None:
            return None

        return client.read_namespaced_deployment(
            name=name,
            namespace=namespace,
            _request_timeout=self._get_request_timeout(timeout_seconds),
        )

    def _read_live_service(
        self, cluster: str, namespace: Optional[str], name: str, timeout_seconds: int
    ):
        client = self._manager.get_core_client(cluster)
        if client is None:
            return None

        return client.read_namespaced_service(
            name=name,
            namespace=namespace,
            _request_timeout=self._get_request_timeout(timeout_seconds),
        )

    def _read_live_job(
        self, cluster: str, namespace: Optional[str], name: str, timeout_seconds: int
    ):
        client = self._manager.get_batch_client(cluster)
        if client is None:
            return None

        return client.read_namespaced_job(
            name=name,
            namespace=namespace,
            _request_timeout=self._get_request_timeout(timeout_seconds),
        )

    def _is_resource_stale(
        self,
        *,
        cluster: str,
        cached_resource=None,
        read_live_resource=None,
        timeout_seconds: int = 120,
    ) -> bool:
        metadata = getattr(cached_resource, "metadata", None) if cached_resource else None
        cached_version = getattr(metadata, "resource_version", None) if metadata else None
        name = getattr(metadata, "name", "unknown") if metadata else "unknown"
        namespace = getattr(metadata, "namespace", "unknown") if metadata else "unknown"
        raw_kind = getattr(cached_resource, "kind", None) if cached_resource else None
        resource_label = (raw_kind or "resource").lower()

        can_check_live = bool(cached_resource and cached_version and read_live_resource)
        live_resource = None
        is_stale = False

        if can_check_live:
            try:
                live_resource = read_live_resource(cluster, namespace, name, timeout_seconds)
            except ApiException as exc:
                if exc.status != 404:
                    reason = f"Failed to read {resource_label} {namespace}/{name} in cluster {cluster}: {exc}"
                    self._redis.mark_cluster_unhealthy(cluster, reason)
                    logger.warning(reason)
                    is_stale = True
                can_check_live = False
            except Exception as exc:
                reason = f"Unexpected error reading {resource_label} {namespace}/{name} in cluster {cluster}: {exc}"
                self._redis.mark_cluster_unhealthy(cluster, reason)
                logger.error(reason)
                is_stale = True
                can_check_live = False

        if can_check_live and live_resource is not None:
            live_metadata = getattr(live_resource, "metadata", None)
            live_version = getattr(live_metadata, "resource_version", None)

            if live_version and live_version != cached_version:
                reason = (
                    f"Resource version mismatch for {resource_label} {namespace}/{name} in cluster {cluster}: "
                    f"cache={cached_version}, cluster={live_version}"
                )
                self._redis.mark_cluster_unhealthy(cluster, reason)
                logger.warning(reason)
                is_stale = True

        return is_stale

    async def get_deployment(self, deployment_id: str) -> Dict:
        """Get a single Chute deployment by ID."""
        deployment_name = f"{CHUTE_DEPLOY_PREFIX}-{deployment_id}"

        resources = self._redis.get_resources(
            resource_type=ResourceType.JOB, resource_name=deployment_name
        )

        # Handle case where no deployments found or more than one found
        if len(resources.jobs) == 0:
            logger.warning(f"Failed to find deployment {deployment_name}")
            raise ApiException(status=404, reason=f"Failed to find deployment {deployment_name}")

        return self._extract_job_info(resources.jobs[0])

    def _wait_for_deployment(self, label_selector: str, timeout_seconds: int = 120) -> None:
        """
        Wait for a deleted pod to be fully removed.
        """
        pods = self.get_pods(settings.namespace, label_selector)
        found = len(pods.items) > 0
        if not found:
            try:
                for event in self.watch_pods(
                    namespace=settings.namespace,
                    label_selector=label_selector,
                    timeout=timeout_seconds,
                ):
                    if not event.is_deleted:
                        logger.success(f"Deployment {label_selector=} is in cache.")
                        found = True
                        break
            except Exception as exc:
                logger.warning(f"Error waiting for deployment to be cached: {exc}")

        if not found:
            raise ApiException(
                status=404, reason=f"Failed to find deployment {label_selector} in cache."
            )

    def _delete_deployment(self, name, namespace=settings.namespace, timeout_seconds: int = 120):
        context, cached_deployment = self._redis.get_resource_with_context(
            resource_type=ResourceType.DEPLOYMENT,
            resource_name=name,
            namespace=namespace,
        )

        if not context:
            logger.warning(f"Attempted to delete deployment {name}, but deployment not found.")
            return

        client = self._manager.get_app_client(context)

        try:
            client.delete_namespaced_deployment(
                name=name,
                namespace=namespace,
                _request_timeout=self._get_request_timeout(timeout_seconds),
            )
        except ApiException as e:
            if e.status == 404:
                # Not found, remove from redis
                self._redis.delete_resource(name, context, ResourceType.DEPLOYMENT, namespace)
                logger.warning(
                    f"Attempted to delete deployment {name}, but appears to have disappeared.  Removed from redis cache."
                )
            else:
                raise

    def _deploy_service(
        self, service, server_name, namespace=settings.namespace, timeout_seconds: int = 60
    ):
        # If the server isn't healthy don't deploy
        self._verify_node_health(server_name)

        client = self._manager.get_core_client(server_name)
        return client.create_namespaced_service(
            namespace=namespace,
            body=service,
            _request_timeout=self._get_request_timeout(timeout_seconds),
        )

    def _delete_service(self, name, namespace=settings.namespace, timeout_seconds: int = 60):
        svc_name = name
        context, cached_service = self._redis.get_resource_with_context(
            resource_type=ResourceType.SERVICE,
            resource_name=svc_name,
            namespace=namespace,
        )

        if not context and CHUTE_SVC_PREFIX in name:
            legacy_name = name.replace(CHUTE_SVC_PREFIX, "chute-svc")
            context, cached_service = self._redis.get_resource_with_context(
                resource_type=ResourceType.SERVICE,
                resource_name=legacy_name,
                namespace=namespace,
            )
            if context:
                svc_name = legacy_name

        if not context:
            logger.warning(f"Attempted to delete service {svc_name}, but context not found.")
            return

        if cached_service is not None and cached_service.metadata:
            svc_name = cached_service.metadata.name

        client = self._manager.get_core_client(context)

        try:
            client.delete_namespaced_service(
                name=svc_name,
                namespace=namespace,
                _request_timeout=self._get_request_timeout(timeout_seconds),
            )
        except ApiException as e:
            if e.status == 404:
                # Not found, remove from redis
                self._redis.delete_resource(svc_name, context, ResourceType.SERVICE, namespace)
                logger.warning(
                    f"Attempted to delete service {svc_name}, but appears to have disappeared.  Removed from redis cache."
                )
            else:
                raise

    def delete_config_map(self, name, namespace=settings.namespace, timeout_seconds: int = 60):
        # Create CM on all clusters
        clusters = self._redis.get_all_cluster_names()
        for cluster in clusters:
            self._delete_config_map_from_cluster(cluster, name, namespace, timeout_seconds)

    def _delete_config_map_from_cluster(
        self, cluster, name, namespace=settings.namespace, timeout_seconds: int = 60
    ):
        if _is_tee_cluster(cluster):
            return
        client = self._manager.get_core_client(cluster)
        # Need to handle 404 per cluster so we don't break out early
        try:
            client.delete_namespaced_config_map(
                name=name,
                namespace=namespace,
                _request_timeout=self._get_request_timeout(timeout_seconds),
            )
        except (MaxRetryError, ConnectionTimeoutError):
            # Cluster is unreachable, CMs will reconcile on reconnect
            pass
        except ApiException as e:
            if e.status != 404:
                raise

    async def _deploy_config_map(
        self,
        config_map: V1ConfigMap,
        namespace=settings.namespace,
        timeout_seconds: int = 60,
        force=False,
    ):
        request = ConfigMapDeployRequest(
            config_map=config_map,
            namespace=namespace,
            timeout_seconds=timeout_seconds,
            force=force,
        )

        if not self._config_map_worker:
            logger.debug(
                f"ConfigMap worker disabled (RECONCILE_CLUSTERS=false); skipping async deploy for {config_map.metadata.name}."
            )
            return

        if not self._config_map_worker.enqueue_deploy(request):
            logger.error(f"ConfigMap worker failed to deploy CM for {config_map.metadata.name}.")

    def _deploy_config_map_to_all_clusters(
        self,
        config_map: V1ConfigMap,
        namespace=settings.namespace,
        timeout_seconds: int = 60,
        force=False,
    ):
        # Create CM on all clusters
        clusters = self._redis.get_all_cluster_names()
        for cluster in clusters:
            self._deploy_config_map_to_cluster(
                cluster, config_map, namespace, timeout_seconds, force
            )

    def _deploy_config_map_to_cluster(
        self,
        cluster: str,
        config_map: V1ConfigMap,
        namespace=settings.namespace,
        timeout_seconds: int = 60,
        force=False,
    ):
        if _is_tee_cluster(cluster):
            return
        try:
            self._verify_node_health(cluster)
            client = self._manager.get_core_client(cluster)
            client.create_namespaced_config_map(
                namespace=namespace,
                body=config_map,
                _request_timeout=self._get_request_timeout(timeout_seconds),
            )
        except (MaxRetryError, ConnectionTimeoutError):
            # Cluster is unreachable, CMs will reconcile on reconnect
            logger.warning(
                f"Failed to deploy {config_map.metadata.name} on cluster {cluster}, unable to connect.  CMs will reconcile on reconnect."
            )
        except ApiException as e:
            # Need to handle 409 per cluster so we don't break out early

            if e.status == 409:
                # Swallow 409 and only replace if force flag is true
                if force:
                    logger.warning(
                        f"Replacing configmap {config_map.metadata.name} on cluster {cluster}."
                    )
                    try:
                        client.delete_namespaced_config_map(
                            name=config_map.metadata.name,
                            namespace=namespace,
                            _request_timeout=self._get_request_timeout(timeout_seconds),
                        )
                        client.create_namespaced_config_map(
                            namespace=namespace,
                            body=config_map,
                            _request_timeout=self._get_request_timeout(timeout_seconds),
                        )
                    except ApiException:
                        logger.error(
                            f"Failed to force replace configmap {config_map.metdata.name} on cluster {cluster}"
                        )
            elif e.status == 503:
                pass
            else:
                # We can just swallow 409s. Other errors shoudl be logged,
                # but still do not want to short circuit
                logger.error(
                    f"Failed to deploy configmap {config_map.metadata.name} to cluster {cluster}:\n{e}"
                )
        except Exception as e:
            logger.error(
                f"Failed to deploy configmap {config_map.metadata.name} to cluster {cluster}.\n{e}"
            )

    def _deploy_job_for_deployment(
        self, job, server_name, namespace=settings.namespace, timeout_seconds=120
    ):
        created_job = self._deploy_job(job, server_name, namespace, timeout_seconds=timeout_seconds)
        deployment_id = job.metadata.labels["chutes/deployment-id"]
        self._wait_for_deployment(
            f"chutes/deployment-id={deployment_id}",
            timeout_seconds=settings.deploy_cache_wait_timeout,
        )
        return created_job

    def _deploy_job(
        self, job, server_name, namespace=settings.namespace, timeout_seconds: int = 120
    ):
        # If the server isn't healthy don't deploy since cache will be out of sync
        self._verify_node_health(server_name)

        client = self._manager.get_batch_client(server_name)
        return client.create_namespaced_job(
            namespace=namespace,
            body=job,
            _request_timeout=self._get_request_timeout(timeout_seconds),
        )

    def _delete_job(self, name, namespace=settings.namespace, timeout_seconds: int = 120):
        context, cached_job = self._redis.get_resource_with_context(
            resource_type=ResourceType.JOB,
            resource_name=name,
            namespace=namespace,
        )

        if not context:
            logger.warning(f"Attempted to delete job {name}, but context not found.")
            return

        client = self._manager.get_batch_client(context)

        try:
            client.delete_namespaced_job(
                name=name,
                namespace=namespace,
                propagation_policy="Foreground",
                grace_period_seconds=settings.chute_shutdown_time_seconds,
                _request_timeout=self._get_request_timeout(timeout_seconds),
            )
        except ApiException as e:
            if e.status == 404:
                # Not found, remove from redis
                self._redis.delete_resource(name, context, ResourceType.JOB, namespace)
                logger.warning(
                    f"Attempted to delete job {name}, but appears to have disappeared.  Removed from redis cache."
                )
            else:
                raise

    def watch_pods(self, namespace=None, label_selector=None, field_selector=None, timeout=120):
        for event in self._watch_resources(
            ResourceType.POD,
            namespace=namespace,
            label_selector=label_selector,
            field_selector=field_selector,
            timeout=timeout,
        ):
            yield event

    def get_pods(
        self,
        namespace: Optional[str] = None,
        label_selector: Optional[Union[str | Dict[str, str]]] = None,
        field_selector: Optional[Union[str | Dict[str, str]]] = None,
        timeout=120,
    ) -> V1PodList:
        resources = self._redis.get_resources(resource_type=ResourceType.POD)

        pod_list = [
            pod
            for pod in resources.pods
            if self._matches_filters(pod, namespace, label_selector, field_selector)
        ]

        return V1PodList(items=pod_list)

    def get_deployments(
        self,
        namespace: Optional[str] = None,
        label_selector: Optional[Union[str | Dict[str, str]]] = None,
        field_selector: Optional[Union[str | Dict[str, str]]] = None,
        timeout=120,
    ):
        resources = self._redis.get_resources(resource_type=ResourceType.DEPLOYMENT)

        deploy_list = [
            deployment
            for deployment in resources.deployments
            if self._matches_filters(deployment, namespace, label_selector, field_selector)
        ]

        return V1DeploymentList(items=deploy_list)

    def watch_deployments(
        self, namespace=None, label_selector=None, field_selector=None, timeout=120
    ):
        for event in self._watch_resources(
            ResourceType.DEPLOYMENT,
            namespace=namespace,
            label_selector=label_selector,
            field_selector=field_selector,
            timeout=timeout,
        ):
            yield event

    def get_jobs(self, namespace=None, label_selector=None, field_selector=None, timeout=120):
        resources = self._redis.get_resources(resource_type=ResourceType.JOB)

        job_list = [
            job
            for job in resources.jobs
            if self._matches_filters(job, namespace, label_selector, field_selector)
        ]

        return V1JobList(items=job_list)

    def _watch_resources(
        self,
        resource_type: ResourceType,
        namespace: Optional[str] = None,
        label_selector: Optional[Union[str | Dict[str, str]]] = None,
        field_selector: Optional[Union[str | Dict[str, str]]] = None,
        timeout=120,
    ):
        pubsub: PubSub = self._redis.subscribe_to_resource_type(resource_type)
        start_time = time.time()

        try:
            while True:
                if time.time() - start_time > timeout:
                    logger.warning(
                        f"Watch timeout waiting for updates on {resource_type.value} after {timeout}s."
                    )
                    break

                message = pubsub.get_message(timeout=1)
                if message and message["type"] == "message":
                    data = json.loads(message["data"])
                    _message = ResourceChangeMessage.from_dict(data)
                    if self._matches_filters(
                        _message.event.object,
                        namespace=namespace,
                        label_selector=label_selector,
                        field_selector=field_selector,
                    ):
                        yield _message.event
                else:
                    time.sleep(1)
        finally:
            pubsub.close()

    def _matches_filters(
        self,
        resource: Union[V1Pod, V1Deployment, V1Node, V1Service],
        namespace: Optional[str] = None,
        label_selector: Optional[Union[str | Dict[str, str]]] = None,
        field_selector: Optional[Union[str | Dict[str, str]]] = None,
    ) -> bool:
        """Check if deployment matches all specified filters."""

        # Namespace filter
        if namespace and resource.metadata.namespace != namespace:
            return False

        # Label selector filter
        if label_selector:
            resource_labels = resource.metadata.labels or {}

            if isinstance(label_selector, str):
                # Parse string label selector (e.g., "app=nginx,version=1.0")
                label_dict = self._parse_label_selector(label_selector)
            else:
                label_dict = label_selector

            # Check if all required labels match
            for key, value in label_dict.items():
                if value and resource_labels.get(key) != value:
                    return False
                elif key not in resource_labels.keys():
                    return False

        # Field selector filter (example implementation for common fields)
        if field_selector:
            if isinstance(field_selector, str):
                field_dict = self._parse_field_selector(field_selector)
            else:
                field_dict = field_selector

            for field_path, expected_value in field_dict.items():
                actual_value = self._get_field_value(resource, field_path)
                if actual_value != expected_value:
                    return False

        return True

    def _parse_label_selector(self, selector: str) -> Dict[str, str]:
        """Parse label selector string into dictionary."""
        labels = {}
        if selector:
            for pair in selector.split(","):
                if "=" in pair:
                    key, value = pair.split("=", 1)
                    labels[key.strip()] = value.strip()
                else:
                    labels[selector.strip()] = None
        return labels

    def _parse_field_selector(self, selector: str) -> Dict[str, str]:
        """Parse field selector string into dictionary."""
        fields = {}
        if selector:
            for pair in selector.split(","):
                if "=" in pair:
                    key, value = pair.split("=", 1)
                    fields[key.strip()] = value.strip()
        return fields

    def _get_field_value(self, deployment, field_path: str):
        """Get field value from deployment using dot notation."""
        obj = deployment
        for part in field_path.split("."):
            if hasattr(obj, "attribute_map"):
                attribute_lookup = {v: k for k, v in obj.attribute_map.items()}
                if part in attribute_lookup:
                    part = attribute_lookup[part]
            if hasattr(obj, part):
                obj = getattr(obj, part)
            else:
                return None
        return obj
