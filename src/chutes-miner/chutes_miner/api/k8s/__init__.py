"""
Helper for kubernetes interactions.
"""

from typing import Any, List, Dict, Tuple, Union
from chutes_common.schemas.deployment import Deployment
from chutes_miner.api.k8s.operator import K8sOperator
from chutes_common.schemas.chute import Chute
from chutes_common.schemas.server import Server
from kubernetes.client import V1Job


async def get_kubernetes_nodes() -> List[Dict]:
    """
    Get all Kubernetes nodes via k8s client, optionally filtering by GPU nodes.
    """
    return await K8sOperator().get_kubernetes_nodes()


async def get_deployment(deployment_id: str):
    """
    Get a single deployment by ID.
    """
    return await K8sOperator().get_deployment(deployment_id)


async def get_deployed_chutes() -> List[Dict]:
    """
    Get all chutes deployments from kubernetes.
    """
    return await K8sOperator().get_deployed_chutes()

async def get_deployed_chutes_legacy() -> List[Dict]:
    """
    Get all chutes deployments from kubernetes.
    """
    return await K8sOperator()._get_chute_deployments()


async def delete_code(chute_id: str, version: str):
    """
    Delete the code configmap associated with a chute & version.
    """
    return await K8sOperator().delete_code(chute_id, version)


async def wait_for_deletion(label_selector: str, timeout_seconds: int = 120):
    """
    Wait for a deleted pod to be fully removed.
    """
    return await K8sOperator().wait_for_deletion(label_selector, timeout_seconds)


async def undeploy(deployment_id: str):
    """
    Delete a deployment, and associated service.
    """
    return await K8sOperator().undeploy(deployment_id)

async def create_code_config_map(chute: Chute):
    """
    Create a ConfigMap to store the chute code.
    """
    return await K8sOperator().create_code_config_map(chute)

async def deploy_chute(
    chute_id: Union[str | Chute], 
    server_id: Union[str | Server],
    token: str = None,
    job_id: str = None,
    config_id: str = None,
    disk_gb: int = 10,
    extra_labels: dict[str, str] = {},
    extra_service_ports: list[dict[str, Any]] = []
) -> Tuple[Deployment, V1Job]:
    """
    Deploy a chute!
    """
    return await K8sOperator().deploy_chute(chute_id, server_id, token, job_id, config_id, disk_gb, extra_labels, extra_service_ports)

async def check_node_has_disk_available(node_name: str, required_disk_gb: int) -> bool:
    """
    Check if a node has sufficient disk space available for a deployment.
    """
    return await K8sOperator().get_node_disk_info(node_name)
    # disk_info = await get_node_disk_info(node_name)
    # return disk_info.get("available_gb", 0) >= required_disk_gb