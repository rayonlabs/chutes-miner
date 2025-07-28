from unittest.mock import Mock
from chutes_common.k8s import ClusterResources
from kubernetes_asyncio.client import (
    V1Deployment, V1ObjectMeta, V1DeploymentSpec,
    V1Service, V1ServiceSpec, V1Pod, V1PodSpec,
    V1Node, V1NodeSpec
)
import pytest

from datetime import datetime
from chutes_common.monitoring.requests import SetClusterResourcesRequest
import pytest


# @pytest.fixture
# def create_cluster_request_data():
#     """Factory fixture to create cluster request data with specified resource counts"""
    
#     def _create_request_data(
#         cluster_name: str = "test-cluster",
#         num_deployments: int = 0,
#         num_services: int = 0,
#         num_pods: int = 0,
#         num_nodes: int = 0
#     ) -> dict:
        
#         def create_mock_deployment(name: str) -> V1Deployment:
#             deployment = Mock(spec=V1Deployment)
#             deployment.metadata = Mock(spec=V1ObjectMeta)
#             deployment.metadata.name = name
#             deployment.spec = Mock(spec=V1DeploymentSpec)
#             return deployment
        
#         def create_mock_service(name: str) -> V1Service:
#             service = Mock(spec=V1Service)
#             service.metadata = Mock(spec=V1ObjectMeta)
#             service.metadata.name = name
#             service.spec = Mock(spec=V1ServiceSpec)
#             return service
        
#         def create_mock_pod(name: str) -> V1Pod:
#             pod = Mock(spec=V1Pod)
#             pod.metadata = Mock(spec=V1ObjectMeta)
#             pod.metadata.name = name
#             pod.spec = Mock(spec=V1PodSpec)
#             return pod
        
#         def create_mock_node(name: str) -> V1Node:
#             node = Mock(spec=V1Node)
#             node.metadata = Mock(spec=V1ObjectMeta)
#             node.metadata.name = name
#             node.spec = Mock(spec=V1NodeSpec)
#             return node
        
#         # Create the specified number of each resource type
#         deployments = [create_mock_deployment(f"deployment-{i}") for i in range(num_deployments)]
#         services = [create_mock_service(f"service-{i}") for i in range(num_services)]
#         pods = [create_mock_pod(f"pod-{i}") for i in range(num_pods)]
#         nodes = [create_mock_node(f"node-{i}") for i in range(num_nodes)]
        
#         return {
#             "cluster_name": cluster_name,
#             "initial_resources": {
#                 "deployments": deployments,
#                 "services": services,
#                 "pods": pods,
#                 "nodes": nodes
#             }
#         }
    
#     return _create_request_data

@pytest.fixture
def create_cluster_request_data(sample_cluster_resources):
    """Factory fixture to create cluster request data with specified resource counts"""
    
    def _create_request_data(
        cluster_name: str = "test-cluster",
        num_deployments: int = 0,
        num_services: int = 0,
        num_pods: int = 0,
        num_nodes: int = 0
    ) -> dict:
        
        # def create_mock_deployment(name: str) -> V1Deployment:
        #     deployment = Mock(spec=V1Deployment)
        #     deployment.metadata = Mock(spec=V1ObjectMeta)
        #     deployment.metadata.name = name
        #     deployment.spec = Mock(spec=V1DeploymentSpec)
        #     return deployment
        
        # def create_mock_service(name: str) -> V1Service:
        #     service = Mock(spec=V1Service)
        #     service.metadata = Mock(spec=V1ObjectMeta)
        #     service.metadata.name = name
        #     service.spec = Mock(spec=V1ServiceSpec)
        #     return service
        
        # def create_mock_pod(name: str) -> V1Pod:
        #     pod = Mock(spec=V1Pod)
        #     pod.metadata = Mock(spec=V1ObjectMeta)
        #     pod.metadata.name = name
        #     pod.spec = Mock(spec=V1PodSpec)
        #     return pod
        
        # def create_mock_node(name: str) -> V1Node:
        #     node = Mock(spec=V1Node)
        #     node.metadata = Mock(spec=V1ObjectMeta)
        #     node.metadata.name = name
        #     node.spec = Mock(spec=V1NodeSpec)
        #     return node
        
        # # Create the specified number of each resource type
        # deployments = [create_mock_deployment(f"deployment-{i}") for i in range(num_deployments)]
        # services = [create_mock_service(f"service-{i}") for i in range(num_services)]
        # pods = [create_mock_pod(f"pod-{i}") for i in range(num_pods)]
        # nodes = [create_mock_node(f"node-{i}") for i in range(num_nodes)]
        
        return SetClusterResourcesRequest(cluster_name=cluster_name, resources=sample_cluster_resources)
    
    return _create_request_data

@pytest.fixture
def sample_k8s_objects():
    """Create actual Kubernetes objects with potential problematic data"""
    from kubernetes_asyncio.client import (
        V1Pod, V1PodSpec, V1PodStatus, V1Container, V1EnvVar,
        V1Deployment, V1DeploymentSpec, V1DeploymentStatus,
        V1Service, V1ServiceSpec, V1ServicePort,
        V1Node, V1NodeSpec, V1NodeStatus, V1NodeCondition, V1NodeSystemInfo,
        V1ObjectMeta, V1LabelSelector, V1PodTemplateSpec, V1ContainerStatus, V1PodCondition
    )
    
    # Create actual V1Pod
    pod = V1Pod(
        api_version="v1",
        kind="Pod",
        metadata=V1ObjectMeta(
            name="test-pod",
            namespace="default",
            uid="abc-123-def",
            labels={"app": "test"},
            annotations={
                "kubectl.kubernetes.io/last-applied-configuration": '{"apiVersion":"v1","kind":"Pod"}',
                "test.annotation": "value"
            },
            creation_timestamp=datetime.now().isoformat()
        ),
        spec=V1PodSpec(
            containers=[
                V1Container(
                    name="test-container",
                    image="nginx:latest",
                    env=[V1EnvVar(name="VAR", value="test")]
                )
            ]
        ),
        status=V1PodStatus(
            phase="Running",
            conditions=[
                V1PodCondition(
                    type="Ready",
                    status="True",
                    last_transition_time=datetime.now().isoformat()
                )
            ],
            container_statuses=[
                V1ContainerStatus(
                    name="test-container",
                    ready=True,
                    restart_count=0,
                    container_id="containerd://abc123",
                    image_id="sha256:def456",
                    image="nginx:latest"
                )
            ]
        )
    )

    # Create actual V1Deployment
    deployment = V1Deployment(
        api_version="apps/v1",
        kind="Deployment",
        metadata=V1ObjectMeta(
            name="test-deployment",
            namespace="default",
            labels={"app": "test-deployment"}
        ),
        spec=V1DeploymentSpec(
            replicas=3,
            selector=V1LabelSelector(
                match_labels={"app": "test"}
            ),
            template=V1PodTemplateSpec(
                metadata=V1ObjectMeta(
                    labels={"app": "test"}
                ),
                spec=V1PodSpec(
                    containers=[
                        V1Container(
                            name="test-container",
                            image="nginx:latest"
                        )
                    ]
                )
            )
        ),
        status=V1DeploymentStatus(
            ready_replicas=3,
            replicas=3,
            available_replicas=3
        )
    )

    # Create actual V1Service
    service = V1Service(
        api_version="v1",
        kind="Service",
        metadata=V1ObjectMeta(
            name="test-service",
            namespace="default",
            labels={"app": "test-service"}
        ),
        spec=V1ServiceSpec(
            ports=[
                V1ServicePort(
                    port=80,
                    protocol="TCP",
                    target_port=8080
                )
            ],
            selector={"app": "test"},
            type="ClusterIP"
        )
    )

    # Create actual V1Node
    node = V1Node(
        api_version="v1",
        kind="Node",
        metadata=V1ObjectMeta(
            name="test-node",
            labels={
                "kubernetes.io/hostname": "test-node",
                "node-role.kubernetes.io/control-plane": ""
            }
        ),
        spec=V1NodeSpec(
            pod_cidr="10.244.0.0/24"
        ),
        status=V1NodeStatus(
            conditions=[
                V1NodeCondition(
                    type="Ready",
                    status="True",
                    last_transition_time=datetime.now().isoformat(),
                    reason="KubeletReady",
                    message="kubelet is posting ready status"
                )
            ],
            node_info=V1NodeSystemInfo(
                kubelet_version="v1.25.0",
                kube_proxy_version="v1.25.0",
                operating_system="linux",
                architecture="amd64",
                boot_id="1234",
                machine_id="1234",
                system_uuid="1234",
                container_runtime_version="containerd://1.6.0",
                kernel_version="5.4.0-100-generic",
                os_image="Ubuntu 20.04.3 LTS"
            )
        )
    )

    return {
        'pod': pod,
        'deployment': deployment,
        'service': service,
        'node': node
    }

@pytest.fixture
def sample_cluster_resources(sample_k8s_objects):
    """Sample cluster resources for testing"""
    return ClusterResources(
            pods=[sample_k8s_objects['pod']],
            deployments=[sample_k8s_objects['deployment']],
            services=[sample_k8s_objects['service']],
            nodes=[sample_k8s_objects['node']]
        )