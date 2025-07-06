"""
Helper for kubernetes interactions.
"""

from typing import List, Dict
from chutes_miner.api.k8s.operator import K8sOperator
from chutes_miner.api.chute.schemas import Chute


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


async def deploy_chute(chute_id: str, server_id: str):
    """
    Deploy a chute!
    """
    return await K8sOperator().deploy_chute(chute_id, server_id)
