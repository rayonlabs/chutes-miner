from unittest.mock import Mock
from kubernetes.client import (
    V1Deployment, V1ObjectMeta, V1DeploymentSpec,
    V1Service, V1ServiceSpec, V1Pod, V1PodSpec,
    V1Node, V1NodeSpec
)
import pytest


@pytest.fixture
def create_cluster_request_data():
    """Factory fixture to create cluster request data with specified resource counts"""
    
    def _create_request_data(
        cluster_name: str = "test-cluster",
        num_deployments: int = 0,
        num_services: int = 0,
        num_pods: int = 0,
        num_nodes: int = 0
    ) -> dict:
        
        def create_mock_deployment(name: str) -> V1Deployment:
            deployment = Mock(spec=V1Deployment)
            deployment.metadata = Mock(spec=V1ObjectMeta)
            deployment.metadata.name = name
            deployment.spec = Mock(spec=V1DeploymentSpec)
            return deployment
        
        def create_mock_service(name: str) -> V1Service:
            service = Mock(spec=V1Service)
            service.metadata = Mock(spec=V1ObjectMeta)
            service.metadata.name = name
            service.spec = Mock(spec=V1ServiceSpec)
            return service
        
        def create_mock_pod(name: str) -> V1Pod:
            pod = Mock(spec=V1Pod)
            pod.metadata = Mock(spec=V1ObjectMeta)
            pod.metadata.name = name
            pod.spec = Mock(spec=V1PodSpec)
            return pod
        
        def create_mock_node(name: str) -> V1Node:
            node = Mock(spec=V1Node)
            node.metadata = Mock(spec=V1ObjectMeta)
            node.metadata.name = name
            node.spec = Mock(spec=V1NodeSpec)
            return node
        
        # Create the specified number of each resource type
        deployments = [create_mock_deployment(f"deployment-{i}") for i in range(num_deployments)]
        services = [create_mock_service(f"service-{i}") for i in range(num_services)]
        pods = [create_mock_pod(f"pod-{i}") for i in range(num_pods)]
        nodes = [create_mock_node(f"node-{i}") for i in range(num_nodes)]
        
        return {
            "cluster_name": cluster_name,
            "initial_resources": {
                "deployments": deployments,
                "services": services,
                "pods": pods,
                "nodes": nodes
            }
        }
    
    return _create_request_data