import math
import uuid
import traceback
import abc
from loguru import logger
from typing import List, Dict, Any, Optional, Type, Tuple
from kubernetes import watch
from kubernetes.client import (
    V1Deployment,
    V1Service,
    V1ObjectMeta,
    V1DeploymentSpec,
    V1DeploymentStrategy,
    V1PodTemplateSpec,
    V1PodSpec,
    V1Container,
    V1ResourceRequirements,
    V1ServiceSpec,
    V1ServicePort,
    V1Probe,
    V1EnvVar,
    V1Volume,
    V1VolumeMount,
    V1ConfigMapVolumeSource,
    V1ConfigMap,
    V1HostPathVolumeSource,
    V1SecurityContext,
    V1EmptyDirVolumeSource,
    V1ExecAction,
)
from kubernetes.client.rest import ApiException
from sqlalchemy import select
from api.exceptions import DeploymentFailure
from api.config import settings
from api.database import get_session
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
    
    def _extract_deployment_info(self, deployment: Any) -> Dict:
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
      pod_label_selector = ",".join(
          [f"{k}={v}" for k, v in deployment.spec.selector.match_labels.items()]
      )
      pods = k8s_core_client().list_namespaced_pod(
          namespace=deployment.metadata.namespace, label_selector=pod_label_selector
      )
      deploy_info["pods"] = []
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
          deploy_info["pods"].append(pod_info)
          deploy_info["node"] = pod.spec.node_name
      return deploy_info

    @abc.abstractmethod
    async def get_kubernetes_nodes(self) -> List[Dict]:
        """Get all Kubernetes nodes via k8s client, optionally filtering by GPU nodes."""
        raise NotImplementedError()
    
    def _extract_node_info(self, node):
        gpu_count = int(node.status.capacity["nvidia.com/gpu"])
        gpu_mem_mb = int(node.metadata.labels.get("nvidia.com/gpu.memory", "32"))
        gpu_mem_gb = int(gpu_mem_mb / 1024)
        cpu_count = (
            int(node.status.capacity["cpu"]) - 2
        )  # leave 2 CPUs for incidentals, daemon sets, etc.
        cpus_per_gpu = (
            1 if cpu_count <= gpu_count else min(4, math.floor(cpu_count / gpu_count))
        )
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
    
    @abc.abstractmethod
    async def get_deployed_chutes(self) -> List[Dict]:
        """Get all chutes deployments from kubernetes."""
        raise NotImplementedError()
    
    @abc.abstractmethod
    async def delete_code(self, chute_id: str, version: str) -> None:
        """Delete the code configmap associated with a chute & version."""
        raise NotImplementedError()
    
    @abc.abstractmethod
    async def wait_for_deletion(self, label_selector: str, timeout_seconds: int = 120) -> None:
        """Wait for a deleted pod to be fully removed."""
        raise NotImplementedError()
    
    @abc.abstractmethod
    async def undeploy(self, deployment_id: str) -> None:
        """Delete a deployment, and associated service."""
        raise NotImplementedError()
    
    @abc.abstractmethod
    async def create_code_config_map(self, chute: Chute) -> None:
        """Create a ConfigMap to store the chute code."""
        raise NotImplementedError()
    
    @abc.abstractmethod
    async def deploy_chute(self, chute_id: str, server_id: str) -> Tuple[Deployment, Any, Any]:
        """Deploy a chute!"""
        raise NotImplementedError()
    
# Legacy single-cluster implementation
class SingleClusterK8sOperator(K8sOperator):
    """Kubernetes operations for legacy single-cluster setup."""

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

    def _get_nodes(self):
        node_list = k8s_core_client().list_node(field_selector=None, label_selector="chutes/worker")
        return node_list

    async def get_deployment(self, deployment_id: str) -> Dict:
        """
        Get a single deployment by ID.
        """
        deployment = k8s_app_client().read_namespaced_deployment(
            namespace=settings.namespace,
            name=f"chute-{deployment_id}",
        )
        return self._extract_deployment_info(deployment)

    async def get_deployed_chutes(self) -> List[Dict]:
        """
        Get all chutes deployments from kubernetes.
        """
        deployments = []
        label_selector = "chutes/chute=true"
        deployment_list = k8s_app_client().list_namespaced_deployment(
            namespace=settings.namespace, label_selector=label_selector
        )
        for deployment in deployment_list.items:
            deployments.append(self._extract_deployment_info(deployment))
            logger.info(
                f"Found chute deployment: {deployment.metadata.name} in namespace {deployment.metadata.namespace}"
            )
        return deployments

    async def delete_code(self, chute_id: str, version: str) -> None:
        """
        Delete the code configmap associated with a chute & version.
        """
        try:
            code_uuid = str(uuid.uuid5(uuid.NAMESPACE_OID, f"{chute_id}::{version}"))
            k8s_core_client().delete_namespaced_config_map(
                name=f"chute-code-{code_uuid}", namespace=settings.namespace
            )
        except ApiException as exc:
            if exc.status != 404:
                logger.error(f"Failed to delete code reference: {exc}")
                raise

    async def wait_for_deletion(self, label_selector: str, timeout_seconds: int = 120) -> None:
        """
        Wait for a deleted pod to be fully removed.
        """
        if (
            not k8s_core_client()
            .list_namespaced_pod(
                namespace=settings.namespace,
                label_selector=label_selector,
            )
            .items
        ):
            logger.info(f"Nothing to wait for: {label_selector}")
            return

        w = watch.Watch()
        try:
            for event in w.stream(
                k8s_core_client().list_namespaced_pod,
                namespace=settings.namespace,
                label_selector=label_selector,
                timeout_seconds=timeout_seconds,
            ):
                if (
                    not k8s_core_client()
                    .list_namespaced_pod(
                        namespace=settings.namespace,
                        label_selector=label_selector,
                    )
                    .items
                ):
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
        code_uuid = str(uuid.uuid5(uuid.NAMESPACE_OID, f"{chute.chute_id}::{chute.version}"))
        config_map = V1ConfigMap(
            metadata=V1ObjectMeta(
                name=f"chute-code-{code_uuid}",
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

    async def deploy_chute(self, chute: Chute, server: Server) -> Tuple[Deployment, Any, Any]:
        """Deploy a chute!"""
        # Make sure the node has capacity.
        # used_ports = get_used_ports(server.name)
        gpus_allocated = 0
        available_gpus = {gpu.gpu_id for gpu in server.gpus if gpu.verified}
        for deployment in server.deployments:
            gpus_allocated += len(deployment.gpus)
            available_gpus -= {gpu.gpu_id for gpu in deployment.gpus}
        if len(available_gpus) - chute.gpu_count < 0:
            raise DeploymentFailure(
                f"Server {server.server_id} name={server.name} cannot allocate {chute.gpu_count} GPUs, already using {gpus_allocated} of {len(server.gpus)}"
            )

        # Immediately track this deployment (before actually creating it) to avoid allocation contention.
        deployment_id = str(uuid.uuid4())
        gpus = list([gpu for gpu in server.gpus if gpu.gpu_id in available_gpus])[: chute.gpu_count]
        async with get_session() as session:
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

        # Create the deployment.
        deployment = build_chute_deployment(deployment_id, chute, server)

        # And the service that exposes it.
        service = build_chute_service(deployment_id, chute)

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
    
    def is_deployment_ready(self, deployment):
        pass

    def _extract_deployment_info(self, deployment: Any) -> Dict:
        pass

    async def get_kubernetes_nodes(self) -> List[Dict]:
        """
        Get all Kubernetes nodes via k8s client, optionally filtering by GPU nodes.
        """
        pass

    def _get_nodes():
        pass

    def _extract_node_info(node):
        gpu_count = int(node.status.capacity["nvidia.com/gpu"])
        gpu_mem_mb = int(node.metadata.labels.get("nvidia.com/gpu.memory", "32"))
        gpu_mem_gb = int(gpu_mem_mb / 1024)
        cpu_count = (
            int(node.status.capacity["cpu"]) - 2
        )  # leave 2 CPUs for incidentals, daemon sets, etc.
        cpus_per_gpu = (
            1 if cpu_count <= gpu_count else min(4, math.floor(cpu_count / gpu_count))
        )
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

    async def get_deployment(self, deployment_id: str) -> Dict:
        """Get a single deployment by ID."""
        pass

    async def get_deployed_chutes(self) -> List[Dict]:
        """Get all chutes deployments from kubernetes."""
        pass

    async def delete_code(self, chute_id: str, version: str) -> None:
        """Delete the code configmap associated with a chute & version."""
        pass

    async def wait_for_deletion(self, label_selector: str, timeout_seconds: int = 120) -> None:
        """Wait for a deleted pod to be fully removed."""
        pass

    async def undeploy(self, deployment_id: str) -> None:
        """Delete a deployment, and associated service."""
        pass
    
    async def create_code_config_map(self, chute: Chute) -> None:
        """Create a ConfigMap to store the chute code."""
        pass

    async def deploy_chute(self, chute_id: str, server_id: str) -> Tuple[Deployment, Any, Any]:
        """Deploy a chute!"""
        pass