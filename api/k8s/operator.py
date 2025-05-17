from functools import lru_cache
import math
import uuid
import traceback
import abc
from loguru import logger
from typing import List, Dict, Any, Optional, Tuple, Union
from kubernetes import watch
from kubernetes.client import (
    V1Deployment,
    V1Service,
    V1Node,
    V1NodeList,
    V1PodList,
    V1ObjectMeta,
    V1DeploymentList,
    V1ConfigMap,
)
from kubernetes.client.rest import ApiException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from api.exceptions import DeploymentFailure
from api.config import k8s_api_client, k8s_custom_objects_client, settings
from api.database import get_session
from api.k8s.constants import (
    CHUTE_CODE_CM_PREFIX,
    CHUTE_DEPLOY_PREFIX,
    CHUTE_SVC_PREFIX,
    SEARCH_DEPLOYMENTS_PATH,
    SEARCH_NODES_PATH,
    SEARCH_PODS_PATH,
)
from api.k8s.karmada.models import (
    ClusterAffinity,
    Placement,
    PropagationPolicy,
    ReplicaScheduling,
    ResourceSelector,
)
from api.k8s.response import ApiResponse
from api.k8s.util import build_chute_deployment, build_chute_service
from api.server.schemas import Server
from api.chute.schemas import Chute
from api.deployment.schemas import Deployment
from api.config import k8s_core_client, k8s_app_client


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
            nodes = k8s_core_client().list_node(label_selector="karmada-control-plane=true")
            if nodes.items:
                cls._instance = super().__new__(KarmadaK8sOperator)
            else:
                cls._instance = super().__new__(SingleClusterK8sOperator)
        except Exception as exc:
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
        pods = self._get_pods(
            namespace=deployment.metadata.namespace, labels=deployment.spec.selector.match_labels
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

    @abc.abstractmethod
    def _get_pods(
        self, namespace: Optional[str] = None, labels: Optional[Union[str | Dict[str, str]]] = None
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
                nodes.append(self._extract_node_info(node))
        except Exception as e:
            logger.error(f"Failed to get Kubernetes nodes: {e}")
            raise
        return nodes

    @abc.abstractmethod
    def _get_nodes(self) -> V1NodeList:
        """
        Retrieve all nodes from the environment
        """
        raise NotImplementedError()

    def _extract_node_info(self, node: V1Node):
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
        node_info = {
            "name": node.metadata.name,
            "validator": node.metadata.labels.get("chutes/validator"),
            "server_id": node.metadata.uid,
            "status": node.status.phase,
            "ip_address": node.metadata.labels.get("chutes/external-ip"),
            "cpu_per_gpu": cpus_per_gpu,
            "memory_gb_per_gpu": memory_gb_per_gpu,
        }
        return node_info

    @abc.abstractmethod
    async def get_deployment(self, deployment_id: str) -> Dict:
        """Get a single deployment by ID."""
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
        """Get all chutes deployments from kubernetes."""
        deployments = []
        deployments_list = self._get_deployments(
            namespace=settings.namespace, labels={"chutes/chute": "true"}
        )
        for deployment in deployments_list.items:
            deployments.append(self._extract_deployment_info(deployment))
            logger.info(
                f"Found chute deployment: {deployment.metadata.name} in namespace {deployment.metadata.namespace}"
            )
        return deployments

    @abc.abstractmethod
    def _get_deployments(
        self, namespace: Optional[str] = None, labels: Optional[Dict[str, str]] = None
    ) -> V1DeploymentList:
        """
        Get deployment, optinally filtering by namespace and labels
        """
        raise NotImplementedError()

    async def delete_code(self, chute_id: str, version: str) -> None:
        """
        Delete the code configmap associated with a chute & version.
        """
        try:
            code_uuid = self._get_code_uuid(chute_id, version)
            k8s_core_client().delete_namespaced_config_map(
                name=f"chute-code-{code_uuid}", namespace=settings.namespace
            )
        except ApiException as exc:
            if exc.status != 404:
                logger.error(f"Failed to delete code reference: {exc}")
                raise

    @lru_cache(maxsize=5)
    def _get_code_uuid(self, chute_id: str, version: str) -> str:
        return str(uuid.uuid5(uuid.NAMESPACE_OID, f"{chute_id}::{version}"))

    async def wait_for_deletion(self, label_selector: str, timeout_seconds: int = 120) -> None:
        """
        Wait for a deleted pod to be fully removed.
        """
        pods = self._get_pods(settings.namespace, label_selector)
        if not pods.items:
            logger.info(f"Nothing to wait for: {label_selector}")
            return

        w = watch.Watch()
        try:
            for event in w.stream(
                self._get_pods,
                namespace=settings.namespace,
                labels=label_selector,
                timeout=timeout_seconds,
            ):
                pods = self._get_pods(settings.namespace, label_selector)
                if not pods.items:
                    logger.success(f"Deletion of {label_selector=} is complete")
                    w.stop()
                    break
        except Exception as exc:
            logger.warning(f"Error waiting for pods to be deleted: {exc}")

    async def undeploy(self, deployment_id: str) -> None:
        """Delete a deployment, and associated service."""
        try:
            k8s_core_client().delete_namespaced_service(
                name=f"chute-service-{deployment_id}",
                namespace=settings.namespace,
            )
        except Exception as exc:
            logger.warning(f"Error deleting deployment service from k8s: {exc}")
        try:
            k8s_app_client().delete_namespaced_deployment(
                name=f"chute-{deployment_id}",
                namespace=settings.namespace,
            )
        except Exception as exc:
            logger.warning(f"Error deleting deployment from k8s: {exc}")
        await self.wait_for_deletion(f"chutes/deployment-id={deployment_id}", timeout_seconds=15)

    async def create_code_config_map(self, chute: Chute) -> None:
        """Create a ConfigMap to store the chute code."""
        code_uuid = self._get_code_uuid(chute.chute_id, chute.version)
        config_map = V1ConfigMap(
            metadata=V1ObjectMeta(
                name=f"{CHUTE_CODE_CM_PREFIX}-{code_uuid}",
                labels={
                    "chutes/chute-id": chute.chute_id,
                    "chutes/version": chute.version,
                },
            ),
            data={chute.filename: chute.code},
        )
        try:
            k8s_core_client().create_namespaced_config_map(
                namespace=settings.namespace, body=config_map
            )
        except ApiException as e:
            if e.status != 409:
                raise

    async def deploy_chute(
        self, chute_id: Union[str | Chute], server_id: Union[str | Server]
    ) -> Tuple[Deployment, Any, Any]:
        """Deploy a chute!"""
        # Backwards compatible types...
        if isinstance(chute_id, Chute):
            chute_id = chute_id.chute_id
        if isinstance(server_id, Server):
            server_id = server_id.server_id

        async with get_session() as session:
            chute = await self._fetch_chute(session, chute_id)
            server = await self._fetch_server(session, server_id)
            available_gpus = self._verify_gpus(chute, server)
            deployment_id = await self._track_deployment(session, chute, server, available_gpus)

        # Create the deployment.
        deployment = build_chute_deployment(deployment_id, chute, server)

        # And the service that exposes it.
        service = build_chute_service(deployment_id, chute)

        return await self._deploy_chute_resources(deployment_id, deployment, service, chute, server)

    async def _fetch_chute(self, session: AsyncSession, chute_id: str):
        chute = (
            (await session.execute(select(Chute).where(Chute.chute_id == chute_id)))
            .unique()
            .scalar_one_or_none()
        )

        if not chute:
            raise DeploymentFailure(f"Failed to find chute: {chute_id=}")

        return chute

    async def _fetch_server(self, session: AsyncSession, server_id: str):
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
        self, session: AsyncSession, chute: Chute, server: Server, available_gpus
    ):
        # Immediately track this deployment (before actually creating it) to avoid allocation contention.
        deployment_id = str(uuid.uuid4())
        gpus = list([gpu for gpu in server.gpus if gpu.gpu_id in available_gpus])[: chute.gpu_count]
        deployment = Deployment(
            deployment_id=deployment_id,
            server_id=server.server_id,
            validator=server.validator,
            chute_id=chute.chute_id,
            version=chute.version,
            active=False,
            verified_at=None,
            stub=True,
        )
        session.add(deployment)
        deployment.gpus = gpus
        await session.commit()

        return deployment_id

    @abc.abstractmethod
    async def _deploy_chute_resources(
        self,
        deployment_id: str,
        deployment: V1Deployment,
        service: V1Service,
        chute: Chute,
        server: Server,
    ):
        raise NotImplementedError()


# Legacy single-cluster implementation
class SingleClusterK8sOperator(K8sOperator):
    """Kubernetes operations for legacy single-cluster setup."""

    def _get_nodes(self):
        """
        Retrieve all nodes from the environment
        """
        node_list = k8s_core_client().list_node(field_selector=None, label_selector="chutes/worker")
        return node_list

    def _get_pods(
        self,
        namespace: Optional[str] = None,
        labels: Optional[Union[str | Dict[str, str]]] = None,
        timeout=120,
    ) -> V1PodList:
        pod_label_selector = (
            labels
            if labels and isinstance(labels, str)
            else ",".join([f"{k}={v}" for k, v in labels.items()])
        )
        pods = k8s_core_client().list_namespaced_pod(
            namespace=namespace, label_selector=pod_label_selector, timeout_seconds=timeout
        )
        return pods

    async def get_deployment(self, deployment_id: str) -> Dict:
        """
        Get a single deployment by ID.
        """
        deployment = k8s_app_client().read_namespaced_deployment(
            namespace=settings.namespace,
            name=f"chute-{deployment_id}",
        )
        return self._extract_deployment_info(deployment)

    def _get_deployments(
        self, namespace: Optional[str] = None, labels: Optional[Dict[str, str]] = None
    ) -> V1DeploymentList:
        """
        Get deployment, optinally filtering by namespace and labels
        """
        label_selector = ",".join([f"{k}={v}" for k, v in labels.items()])
        deployment_list = k8s_app_client().list_namespaced_deployment(
            namespace=namespace, label_selector=label_selector
        )
        return deployment_list

    async def _deploy_chute_resources(
        self,
        deployment_id: str,
        deployment: V1Deployment,
        service: V1Service,
        chute: Chute,
        server: Server,
    ):
        try:
            created_service = k8s_core_client().create_namespaced_service(
                namespace=settings.namespace, body=service
            )
            created_deployment = k8s_app_client().create_namespaced_deployment(
                namespace=settings.namespace, body=deployment
            )
            deployment_port = created_service.spec.ports[0].node_port
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

            return deployment, created_deployment, created_service
        except ApiException as exc:
            try:
                k8s_core_client().delete_namespaced_service(
                    name=f"chute-service-{deployment_id}",
                    namespace=settings.namespace,
                )
            except Exception:
                ...
            try:
                k8s_core_client().delete_namespaced_deployment(
                    name=f"chute-{deployment_id}",
                    namespace=settings.namespace,
                )
            except Exception:
                ...
            raise DeploymentFailure(
                f"Failed to deploy chute {chute.chute_id} with version {chute.version}: {exc}\n{traceback.format_exc()}"
            )


class KarmadaK8sOperator(K8sOperator):
    """Kubernetes operations for Karmada-based multi-cluster setup."""

    # This class will implement the K8sOperator interface but translate operations
    # to work with Karmada's multi-cluster orchestration

    @property
    def karmada_api_client(self):
        return k8s_api_client(context="karmada-apiserver")

    @property
    def karmada_custom_objects_client(self):
        return k8s_custom_objects_client(context="karmada-apiserver")

    def _get_nodes(self) -> V1NodeList:
        response = self._search(SEARCH_NODES_PATH)
        node_list = self.karmada_api_client.deserialize(ApiResponse(response), "V1NodeList")
        return node_list

    async def get_deployment(self, deployment_id: str) -> Dict:
        """Get a single deployment by ID."""
        # Initialize query parameters
        query_params = {}
        query_params["fieldSelector"] = (
            f"metadata.namespace={settings.namespace},metadata.name=chute-{deployment_id}"
        )

        response = self._search(SEARCH_DEPLOYMENTS_PATH, query_params)
        deploy_list = self.karmada_api_client.deserialize(ApiResponse(response), "V1DeploymentList")
        # Handle case where no deployments found or more than one found
        return self._extract_deployment_info(deploy_list.items[0])

    async def delete_code(self, chute_id: str, version: str) -> None:
        """Delete the code configmap associated with a chute & version."""
        await super().delete_code(chute_id, version)
        code_uuid = self._get_code_uuid(chute_id, version)
        self._delete_propagation_policy(settings.namespace, code_uuid)

    async def undeploy(self, deployment_id: str) -> None:
        """Delete a deployment, and associated service."""
        await super().undeploy(deployment_id)
        service_pp_name = f"chute-service-pp-{deployment_id}"
        deployment_pp_name = f"chute-pp-{deployment_id}"
        self._delete_propagation_policy(settings.namespace, service_pp_name)
        self._delete_propagation_policy(settings.namespace, deployment_pp_name)

    async def _deploy_chute_resources(
        self,
        deployment_id: str,
        deployment: V1Deployment,
        service: V1Service,
        chute: Chute,
        server: Server,
    ):
        try:
            created_service = k8s_core_client().create_namespaced_service(
                namespace=settings.namespace, body=service
            )
            created_deployment = k8s_app_client().create_namespaced_deployment(
                namespace=settings.namespace, body=deployment
            )
            self._create_chute_service_propagation_policy(deployment_id, service, server)
            self._create_chute_deployment_propagation_policy(deployment_id, deployment, server)
            self._create_chute_code_cm_propagation_policy(deployment_id, chute, server)
            deployment_port = created_service.spec.ports[0].node_port
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

            return deployment, created_deployment, created_service
        except ApiException as exc:
            try:
                self._cleanup_chute_resources(deployment_id, chute)
            except Exception:
                ...

            raise DeploymentFailure(
                f"Failed to deploy chute {chute.chute_id} with version {chute.version}: {exc}\n{traceback.format_exc()}"
            )

    def _cleanup_chute_resources(self, deployment_id: str, chute: Chute):
        code_uuid = self._get_code_uuid(chute.chute_id, chute.version)
        service_pp_name = f"{CHUTE_SVC_PREFIX}-{deployment_id}"
        deployment_pp_name = f"{CHUTE_DEPLOY_PREFIX}-{deployment_id}"
        code_cm_pp_name = f"{CHUTE_CODE_CM_PREFIX}-{code_uuid}"

        try:
            k8s_core_client().delete_namespaced_service(
                name=f"chute-service-{deployment_id}",
                namespace=settings.namespace,
            )
        except Exception:
            ...
        try:
            k8s_core_client().delete_namespaced_deployment(
                name=f"chute-{deployment_id}",
                namespace=settings.namespace,
            )
        except Exception:
            ...
        try:
            self._delete_propagation_policy(settings.namespace, service_pp_name)
        except Exception:
            ...

        try:
            self._delete_propagation_policy(settings.namespace, deployment_pp_name)
        except Exception:
            ...

        try:
            self._delete_propagation_policy(settings.namespace, code_cm_pp_name)
        except Exception:
            ...

    def _create_chute_deployment_propagation_policy(
        self, deployment_id: str, deployment: V1Deployment, server: Server
    ):
        pp = PropagationPolicy(
            name=f"{CHUTE_DEPLOY_PREFIX}-{deployment_id}",
            namespace=settings.namespace,
            resource_selectors=[
                ResourceSelector(api_version="v1", kind="Deployment", name=deployment.metadata.name)
            ],
            placement=Placement(
                cluster_affinity=ClusterAffinity(cluster_names=[server.name]),
                replica_scheduling=ReplicaScheduling(scheduling_type="Duplicated"),
            ),
        )
        self._create_propagation_policy(settings.namespace, pp)

    def _create_chute_service_propagation_policy(
        self, deployment_id: str, service: V1Service, server: Server
    ):
        pp = PropagationPolicy(
            name=f"{CHUTE_SVC_PREFIX}-{deployment_id}",
            namespace=settings.namespace,
            resource_selectors=[
                ResourceSelector(api_version="v1", kind="Service", name=service.metadata.name)
            ],
            placement=Placement(
                cluster_affinity=ClusterAffinity(cluster_names=[server.name]),
                replica_scheduling=ReplicaScheduling(scheduling_type="Duplicated"),
            ),
        )
        self._create_propagation_policy(settings.namespace, pp)

    def _create_chute_code_cm_propagation_policy(
        self, deployment_id: str, chute: Chute, server: Server
    ):
        code_uuid = self._get_code_uuid(chute.chute_id, chute.version)
        pp = PropagationPolicy(
            name=f"{CHUTE_CODE_CM_PREFIX}-{deployment_id}",
            namespace=settings.namespace,
            resource_selectors=[
                ResourceSelector(
                    api_version="v1", kind="ConfigMap", name=f"{CHUTE_CODE_CM_PREFIX}-{code_uuid}"
                )
            ],
            placement=Placement(
                cluster_affinity=ClusterAffinity(cluster_names=[server.name]),
                replica_scheduling=ReplicaScheduling(scheduling_type="Duplicated"),
            ),
        )
        self._create_propagation_policy(settings.namespace, pp)

    def _create_propagation_policy(self, namespace: str, propagation_policy: PropagationPolicy):
        self.karmada_custom_objects_client.create_namespaced_custom_object(
            group="policy.karmada.io",
            version="v1alpha1",
            namespace=namespace,
            plural="propagationpolicies",
            body=propagation_policy.to_dict(),
        )

    def _delete_propagation_policy(self, namespace, pp_name):
        self.karmada_custom_objects_client.delete_namespaced_custom_object(
            group="policy.karmada.io",
            version="v1alpha1",
            namespace=namespace,
            plural="propagationpolicies",
            name=pp_name,
        )

    def _get_pods(
        self, namespace: Optional[str] = None, labels: Optional[Union[str | Dict[str, str]]] = None
    ) -> V1PodList:
        # Initialize query parameters
        query_params = {}

        # Add namespace filter if specified
        if namespace:
            query_params["fieldSelector"] = f"metadata.namespace={namespace}"

        # Add label selector if specified
        if labels:
            # Convert dictionary of labels to string format
            # Example: {'app': 'nginx', 'tier': 'frontend'} -> 'app=nginx,tier=frontend'
            label_selector = (
                labels
                if isinstance(labels, str)
                else ",".join([f"{k}={v}" for k, v in labels.items()])
            )
            query_params["labelSelector"] = label_selector

        response = self._search(SEARCH_PODS_PATH, query_params)
        pod_list = self.karmada_api_client.deserialize(ApiResponse(response), "V1PodList")
        return pod_list

    def _get_deployments(
        self, namespace: Optional[str] = None, labels: Optional[Dict[str, str]] = None
    ):
        # Initialize query parameters
        query_params = {}

        # Add namespace filter if specified
        if namespace:
            query_params["fieldSelector"] = f"metadata.namespace={namespace}"

        # Add label selector if specified
        if labels:
            # Convert dictionary of labels to string format
            # Example: {'app': 'nginx', 'tier': 'frontend'} -> 'app=nginx,tier=frontend'
            label_selector = ",".join([f"{k}={v}" for k, v in labels.items()])
            query_params["labelSelector"] = label_selector

        response = self._search(SEARCH_DEPLOYMENTS_PATH, query_params)
        deploy_list = self.karmada_api_client.deserialize(ApiResponse(response), "V1DeploymentList")
        return deploy_list

    def _search(self, api_path, query_params={}):
        """
        Search using the Karamada Search API
        """

        response = self.karmada_api_client.call_api(
            api_path,
            "GET",
            query_params=query_params,
            response_type="object",
            _return_http_data_only=True,
        )

        return response
