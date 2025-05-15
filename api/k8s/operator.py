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

    @abc.abstractmethod
    async def get_kubernetes_nodes(self) -> List[Dict]:
        """Get all Kubernetes nodes via k8s client, optionally filtering by GPU nodes."""
        pass
    
    @abc.abstractmethod
    async def get_deployment(self, deployment_id: str) -> Dict:
        """Get a single deployment by ID."""
        pass
    
    @abc.abstractmethod
    async def get_deployed_chutes(self) -> List[Dict]:
        """Get all chutes deployments from kubernetes."""
        pass
    
    @abc.abstractmethod
    async def delete_code(self, chute_id: str, version: str) -> None:
        """Delete the code configmap associated with a chute & version."""
        pass
    
    @abc.abstractmethod
    async def wait_for_deletion(self, label_selector: str, timeout_seconds: int = 120) -> None:
        """Wait for a deleted pod to be fully removed."""
        pass
    
    @abc.abstractmethod
    async def undeploy(self, deployment_id: str) -> None:
        """Delete a deployment, and associated service."""
        pass
    
    @abc.abstractmethod
    async def create_code_config_map(self, chute: Chute) -> None:
        """Create a ConfigMap to store the chute code."""
        pass
    
    @abc.abstractmethod
    async def deploy_chute(self, chute_id: str, server_id: str) -> Tuple[Deployment, Any, Any]:
        """Deploy a chute!"""
        pass
    
# Legacy single-cluster implementation
class SingleClusterK8sOperator(K8sOperator):
    """Kubernetes operations for legacy single-cluster setup."""

    def is_deployment_ready(self, deployment):
        pass

    def _extract_deployment_info(self, deployment: Any) -> Dict:
        pass

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