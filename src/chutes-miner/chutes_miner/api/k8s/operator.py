import asyncio
from datetime import datetime, timedelta
from functools import lru_cache
import json
import math
import re
import time
import uuid
import traceback
import abc
import semver
from chutes_common.monitoring.messages import ClusterChangeMessage, ResourceChangeMessage
from chutes_common.monitoring.models import ResourceType
from chutes_common.redis import MonitoringRedisClient
from chutes_miner.api.k8s.client import KubernetesMultiClusterClientManager
from chutes_miner.api.k8s.config import KubeConfig
from loguru import logger
from typing import Generator, List, Dict, Any, Optional, Tuple, Union
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
    V1JobList
)
from kubernetes.client.rest import ApiException
from kubernetes.client import CoreV1Api
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from chutes_miner.api.exceptions import DeploymentFailure
from chutes_miner.api.database import get_session
from chutes_miner.api.k8s.constants import (
    CHUTE_CODE_CM_PREFIX,
    CHUTE_DEPLOY_PREFIX,
    CHUTE_SVC_PREFIX,
    GRAVAL_JOB_PREFIX,
    GRAVAL_SVC_PREFIX,
)
from chutes_common.k8s import WatchEvent, WatchEventType
from chutes_miner.api.k8s.util import build_chute_job, build_chute_service
from chutes_miner.api.server.schemas import Server
from chutes_miner.api.chute.schemas import Chute
from chutes_miner.api.deployment.schemas import Deployment
from chutes_miner.api.config import k8s_core_client, k8s_app_client, k8s_batch_client, settings
from redis.client import PubSub
import yaml

# Cache disk stats.
_disk_info_cache: dict[str, tuple[dict[str, float], datetime]] = {}
_disk_info_locks: dict[str, asyncio.Lock] = {}


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
            nodes = k8s_core_client().list_node(label_selector="node.kubernetes.io/instance-type=k3s")
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
        pod_label_selector = f"chutes/deployment-id={job.metadata.labels.get('chutes/deployment-id')}"
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
            "node": job.spec.template.spec.node_name
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

        pod_label_selector = f"chutes/deployment-id={job.metadata.labels.get('chutes/deployment-id')}"
        pods = self.get_pods(namespace=job.metadata.namespace, label_selector=pod_label_selector)
        job_info["pods"] = []
        for pod in pods.items:
            state = pod.status.container_statuses[0].state if pod.status.container_statuses else None
            last_state = (
                pod.status.container_statuses[0].last_state if pod.status.container_statuses else None
            )
            pod_info = {
                "name": pod.metadata.name,
                "phase": pod.status.phase,
                "restart_count": pod.status.container_statuses[0].restart_count
                if pod.status.container_statuses
                else 0,
                "state": {
                    "running": state.running.to_dict() if state and state.running else None,
                    "terminated": state.terminated.to_dict() if state and state.terminated else None,
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
            for node in node_list.items:
                node_info = await self._extract_node_info(node)
                nodes.append(node_info)
        except Exception as e:
            logger.error(f"Failed to get Kubernetes nodes: {e}")
            raise
        return nodes

    @abc.abstractmethod
    def get_node(self, name: str, kubeconfig: Optional[str] = None) -> V1Node:
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
    def patch_node(self, name: str, body: Dict) -> V1Node:
        raise NotImplementedError()

    async def _extract_node_info(self, node: V1Node):
        if not node.status.capacity or not node.status.capacity.get("nvidia.com/gpu"):
            logger.warning(f"Node has no GPU capacity: {node.metadata.name=}")
            return None
        
        gpu_count = int(node.status.capacity["nvidia.com/gpu"])
        gpu_mem_mb = int(node.metadata.labels.get("nvidia.com/gpu.memory", "32"))
        gpu_mem_gb = int(gpu_mem_mb / 1024)
        cpu_count = (
            int(node.status.capacity["cpu"]) - 2
        )  # leave 2 CPUs for incidentals, daemon sets, etc.
        cpus_per_gpu = 1 if cpu_count <= gpu_count else min(4, math.floor(cpu_count / gpu_count))
        raw_mem = node.status.capacity["memory"]
        if raw_mem.endswith("Ki"):
            total_memory_gb = int(int(raw_mem.replace("Ki", "")) / 1024 / 1024) - 6
        elif raw_mem.endswith("Mi"):
            total_memory_gb = int(int(raw_mem.replace("Mi", "")) / 1024) - 6
        elif raw_mem.endswith("Gi"):
            total_memory_gb = int(raw_mem.replace("Gi", "")) - 6
        memory_gb_per_gpu = (
            1
            if total_memory_gb <= gpu_count
            else min(gpu_mem_gb, math.floor(total_memory_gb * 0.8 / gpu_count))
        )
        
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
            "disk_used_gb": disk_info.get("used_gb", 0)
        }
        return node_info

    @abc.abstractmethod
    async def get_deployment(self, deployment_id: str) -> Dict:
        """Get a single deployment by ID."""
        raise NotImplementedError()

    @abc.abstractmethod
    def _delete_deployment(self, name: str, namespace: str = settings.namespace):
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
        job_list = self.get_jobs(
            namespace=settings.namespace,
            label_selector=label_selector
        )
        for job in job_list.items:
            jobs.append(self._extract_job_info(job))
            logger.info(f"Found chute job: {job.metadata.name} in namespace {job.metadata.namespace}")
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
    def delete_config_map(self, name: str, namespace=settings.namespace):
        raise NotImplementedError()

    @lru_cache(maxsize=5)
    def _get_code_uuid(self, chute_id: str, version: str) -> str:
        return str(uuid.uuid5(uuid.NAMESPACE_OID, f"{chute_id}::{version}"))

    async def wait_for_deletion(self, label_selector: str, timeout_seconds: int = 120) -> None:
        """
        Wait for a deleted pod to be fully removed.
        """
        pods = self.get_pods(settings.namespace, label_selector)
        if not pods.items:
            logger.info(f"Nothing to wait for: {label_selector}")
            return

        try:
            for event in self.watch_pods(
                namespace=settings.namespace, label_selector=label_selector, timeout=timeout_seconds
            ):
                if event.is_deleted:
                    logger.success(f"Deletion of {label_selector=} is complete")
                    break
        except Exception as exc:
            logger.warning(f"Error waiting for pods to be deleted: {exc}")
            raise

    async def undeploy(self, deployment_id: str) -> None:
        """
        Delete a job, and associated service.
        """
        node_name = None
        try:
            job = await self.get_deployment(
                deployment_id=deployment_id
            )
            node_name = job.get("node", None)
        except Exception:
            pass

        try:
            if node_name:
                self._delete_job(
                    name=f"{CHUTE_DEPLOY_PREFIX}-{deployment_id}",
                    namespace=settings.namespace
                )
            else:
                # Handle fallback to cleaning up old deployments, from instances
                # Created before the 2025-07-17 upgrade.
                self._delete_deployment(
                    name=f"{CHUTE_DEPLOY_PREFIX}-{deployment_id}",
                    namespace=settings.namespace
                )
        except Exception as exc:
            logger.warning(f"Error deleting deployment from k8s: {exc}")

        try:
            self._delete_service(f"{CHUTE_SVC_PREFIX}-{deployment_id}")
        except Exception as exc:
            logger.warning(f"Error removing primary service {CHUTE_SVC_PREFIX}-{deployment_id}: {exc}")

        await self.wait_for_deletion(f"chutes/deployment-id={deployment_id}", timeout_seconds=15)
        
        if node_name:
            self.invalidate_node_disk_cache(node_name)
        

    @abc.abstractmethod
    def _deploy_service(self, service: V1Service, server_name: Optional[str] = None, namespace=settings.namespace):
        raise NotImplementedError()

    @abc.abstractmethod
    def _delete_service(self, name, namespace=settings.namespace):
        raise NotImplementedError()
    
    @abc.abstractmethod
    def _deploy_job(self, job: V1Job, server_name: Optional[str] = None, namespace=settings.namespace):
        raise NotImplementedError()

    @abc.abstractmethod
    def _delete_job(self, name, namespace=settings.namespace):
        raise NotImplementedError()

    async def create_code_config_map(self, chute: Chute) -> None:
        """Create a ConfigMap to store the chute code."""
        try:
            config_map = self._build_code_config_map(chute)
            self._deploy_config_map(config_map)
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
    def _deploy_config_map(self, config_map: V1ConfigMap, namespace=settings.namespace):
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
        extra_service_ports: list[dict[str, Any]] = []
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
            service = self._create_service_for_deployment(chute, server, deployment_id, extra_service_ports)

            # Create the deployment.
            job = self._create_job_for_deployment(
                deployment_id, chute, server, service, 
                gpu_uuids, token, config_id, disk_gb
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
            except:
                ...

            try:
                if job:
                    self._delete_job(job.metadata.name)
            except:
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
        # Make sure the node has capacity.
        gpus_allocated = 0
        available_gpus = {gpu.gpu_id for gpu in server.gpus if gpu.verified}
        for deployment in server.deployments:
            gpus_allocated += len(deployment.gpus)
            available_gpus -= {gpu.gpu_id for gpu in deployment.gpus}
        if len(available_gpus) - chute.gpu_count < 0:
            raise DeploymentFailure(
                f"Server {server.server_id} name={server.name} cannot allocate {chute.gpu_count} GPUs, already using {gpus_allocated} of {len(server.gpus)}"
            )
        return available_gpus

    async def _track_deployment(
        self, session: AsyncSession, chute: Chute, server: Server, available_gpus, job_id: str = None, config_id: str = None
    ):
        # Immediately track this deployment (before actually creating it) to avoid allocation contention.
        deployment_id = str(uuid.uuid4())
        gpus = list([gpu for gpu in server.gpus if gpu.gpu_id in available_gpus])[: chute.gpu_count]
        gpu_uuids = [f"GPU-{str(uuid.UUID(gpu.gpu_id))}" for gpu in gpus]
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
            config_id=config_id
        )
        session.add(deployment)
        deployment.gpus = gpus
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
        probe_port=8000
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
                pods = self.get_pods(
                    field_selector=f"spec.nodeName={node_name}"
                )
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
                                        used_disk_gb += float(ephemeral_storage.replace("M", "")) / 1024
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
                                        used_disk_gb += float(ephemeral_storage.replace("M", "")) / 1024
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
    
    def _create_service_for_deployment(self, chute: Chute, server: Server, deployment_id: str, extra_service_ports: list[dict[str, Any]] = []):
        service = build_chute_service(chute, deployment_id, extra_service_ports)

        try:
            created_service = self._deploy_service(service, server_name=server.name)
        except Exception:
            raise DeploymentFailure(
                f"Failed to create service for {chute.chute_id=} and {deployment_id=}"
            )
        
        return created_service
    
    def _create_job_for_deployment(
        self, deployment_id, chute: Chute, server: Server, service: V1Service, 
        gpu_uuids: list[str], token: Optional[str] = None, 
        config_id: Optional[str] = None, disk_gb: int  = 10
    ) -> V1Job:
        probe_port = self._get_probe_port(chute)
        job = build_chute_job(
                deployment_id, chute, server, service, 
                gpu_uuids, probe_port, token, config_id, disk_gb
            )        

        try:
            created_job = self._deploy_job(job, server_name=server.name)
        except Exception:
            raise DeploymentFailure(
                f"Failed to create job for {chute.chute_id=} and {deployment_id=}"
            )
        
        return created_job


# Legacy single-cluster implementation
class SingleClusterK8sOperator(K8sOperator):
    """Kubernetes operations for legacy single-cluster setup."""

    def get_node(self, name: str, kubeconfig: Optional[str] = None) -> V1Node:
        """
        Retrieve all nodes from the environment
        """
        if kubeconfig:
            raise RuntimeError(
                "Can not retrieve node using kubeconfig in single cluster environment. Do not provide an IP address when adding a node."
            )
        return k8s_core_client().read_node(name=name)

    def _get_nodes(self):
        """
        Retrieve all nodes from the environment
        """
        node_list = k8s_core_client().list_node(field_selector=None, label_selector="chutes/worker")
        return node_list

    def patch_node(self, name, body):
        return k8s_core_client().patch_node(name=name, body=body)

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
        for event in watch.Watch().stream(
            k8s_core_client().list_namespaced_pod,
            namespace=namespace,
            label_selector=label_selector,
            field_selector=field_selector,
            timeout_seconds=timeout,
        ):
            yield WatchEvent.from_dict(event)

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

        pods = k8s_core_client().list_namespaced_pod(
            namespace=namespace,
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
        for event in watch.Watch().stream(
            k8s_app_client().list_namespaced_deployment,
            namespace=namespace,
            label_selector=label_selector,
            field_selector=field_selector,
            timeout_seconds=timeout,
        ):
            yield WatchEvent.from_dict(event)

    def _delete_deployment(self, name, namespace=settings.namespace):
        k8s_app_client().delete_namespaced_deployment(
            name=name,
            namespace=namespace,
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

    def _deploy_service(self, service, server_name = None, namespace=settings.namespace):
        return k8s_core_client().create_namespaced_service(
            namespace=namespace,
            body=service
        )

    def _delete_service(self, name, namespace=settings.namespace):
        k8s_core_client().delete_namespaced_service(
            name=name,
            namespace=namespace,
        )

    def _deploy_job(self, job, server_name = None, namespace=settings.namespace):
        return k8s_batch_client().create_namespaced_job(
            namespace=namespace,
            body=job
        )

    def _delete_job(self, name, namespace=settings.namespace):
        k8s_batch_client().delete_namespaced_job(
            name=name,
            namespace=namespace,
            propagation_policy="Foreground"
        )

    def delete_config_map(self, name, namespace=settings.namespace):
        k8s_core_client().delete_namespaced_config_map(name=name, namespace=namespace)

    def _deploy_config_map(self, config_map: V1ConfigMap, namespace=settings.namespace):
        k8s_core_client().create_namespaced_config_map(namespace=namespace, body=config_map)


class MultiClusterK8sOperator(K8sOperator):
    """Kubernetes operations for multi-cluster setup."""

    # This class will implement the K8sOperator interface but translate operations
    # to work with Karmada's multi-cluster orchestration
    def __init__(self):
        self._manager = KubernetesMultiClusterClientManager()
        self._redis = MonitoringRedisClient()
        self._initialize()

    def _initialize(self):
        # Ugly pattern to ensure we don't kick this off every time singleton is called.
        if not hasattr(self, "_cluster_monitor_task"):
            self._cluster_monitor_task = asyncio.create_task(self._watch_clusters())

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
                    server = (await session.execute(
                        select(Server)
                        .where(Server.name == message.cluster))
                    ).unique().scalar_one_or_none()

                    if server:
                        if server.kubeconfig:
                            self._manager.multi_config.add_config(KubeConfig.from_dict(yaml.safe_load(server.kubeconfig)))
                        else:
                            logger.warning(f"Received add event for cluster {message.cluster} but no kubeconfig is set in DB.")
                    else:
                        logger.warning(f"Received add event for cluster {message.cluster}, but does not exist in DB")
        except Exception as e:
            logger.error(f"Unexpected exception while handling cluster change:\n{e}")


    def get_node(self, name: str, kubeconfig: Optional[KubeConfig] = None) -> V1Node:
        """
        Retrieve a node from the cluster by name.
        """
        _client: CoreV1Api = self._manager.get_core_client(context_name=name, kubeconfig=kubeconfig)

        return _client.read_node(name=name)

    def _get_nodes(self) -> V1NodeList:
        resources = self._redis.get_resources(resource_type=ResourceType.NODE)
        return V1NodeList(items=resources.nodes)

    def patch_node(self, name: str, body: Dict) -> V1Node:
        # cluster = self._redis.get_resource_cluster(resource_name=name, resource_type="node")
        # We can assume the node name is the same as the context, if this changes this will break
        client = self._manager.get_core_client(context_name=name)
        client.patch_node(name=name, body=body)

        return self.get_node(name)

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

    def _delete_deployment(self, name, namespace=settings.namespace):
        context = self._redis.get_resource_cluster(
            resource_name=name, resource_type=ResourceType.DEPLOYMENT, namespace=namespace
        )
        client = self._manager.get_app_client(context)

        try:
            client.delete_namespaced_deployment(
                name=name,
                namespace=namespace,
            )
        except ApiException as e:
            if e.status == 404:
                # Not found, remove from redis
                self._redis.delete_resource(name, context, ResourceType.DEPLOYMENT)
                logger.warning(f"Attempted to delete deployment {name}, but appears to have disappeared.  Removed from redis cache.")
            else:
                raise

    def _deploy_service(self, service, server_name, namespace=settings.namespace):
        client = self._manager.get_core_client(server_name)
        return client.create_namespaced_service(
            namespace=namespace,
            body=service
        )

    def _delete_service(self, name, namespace=settings.namespace):
        context = self._redis.get_resource_cluster(
            resource_name=name, resource_type=ResourceType.SERVICE, namespace=namespace
        )
        client = self._manager.get_core_client(context)
        try:
            client.delete_namespaced_service(
                name=name,
                namespace=namespace,
            )
        except ApiException as e:
            if e.status == 404:
                # Not found, remove from redis
                self._redis.delete_resource(name, context, ResourceType.SERVICE)
                logger.warning(f"Attempted to delete service {name}, but appears to have disappeared.  Removed from redis cache.")
            else:
                raise

    def delete_config_map(self, name, namespace=settings.namespace):
        context = self._redis.get_resource_cluster(
            resource_name=name, resource_type=ResourceType.SERVICE, namespace=namespace
        )
        client = self._manager.get_core_client(context)
        client.delete_namespaced_config_map(
            name=name,
            namespace=namespace,
        )

    def _deploy_config_map(self, config_map: V1ConfigMap, namespace=settings.namespace):
        # Create CM on all clusters
        clusters = self._redis.get_all_cluster_names()
        for cluster in clusters:
            client = self._manager.get_core_client(cluster)
            client.create_namespaced_config_map(namespace=namespace, body=config_map)

    def _deploy_job(self, job, server_name, namespace=settings.namespace):
        client = self._manager.get_batch_client(server_name)
        return client.create_namespaced_job(
            namespace=namespace,
            body=job
        )

    def _delete_job(self, name, namespace=settings.namespace):
        context = self._redis.get_resource_cluster(
            resource_name=name, resource_type=ResourceType.JOB, namespace=namespace
        )
        client = self._manager.get_batch_client(context)
        
        try:
            client.delete_namespaced_job(
                name=name,
                namespace=namespace,
                propagation_policy="Foreground"
            )
        except ApiException as e:
            if e.status == 404:
                # Not found, remove from redis
                self._redis.delete_resource(name, context, ResourceType.JOB)
                logger.warning(f"Attempted to delete job {name}, but appears to have disappeared.  Removed from redis cache.")
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

    def get_jobs(self, namespace = None, label_selector = None, field_selector = None, timeout=120):
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
                    logger.warning(f"Watch timeout waiting for updates on {resource_type.value} after {timeout}s.")
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
            if hasattr(obj, 'attribute_map'):
                attribute_lookup = { v: k for k, v in obj.attribute_map.items() }
                if part in attribute_lookup:
                    part = attribute_lookup[part]
            if hasattr(obj, part):
                obj = getattr(obj, part)
            else:
                return None
        return obj
