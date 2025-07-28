from collections import namedtuple
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from chutes_common.k8s import ClusterResources
import pytest


@pytest.fixture
def sample_k8s_objects():
    """Create actual kubernetes_asyncio objects with potential problematic data"""
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
                "kubectl.kubernetes_asyncio.io/last-applied-configuration": '{"apiVersion":"v1","kind":"Pod"}',
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
                "kubernetes_asyncio.io/hostname": "test-node",
                "node-role.kubernetes_asyncio.io/control-plane": ""
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
def cluster_resources_with_objects(sample_k8s_objects):
    """Create ClusterResources with sample objects"""
    return ClusterResources(
        pods=[sample_k8s_objects['pod']],
        deployments=[sample_k8s_objects['deployment']],
        services=[sample_k8s_objects['service']],
        nodes=[sample_k8s_objects['node']]
    )

MockWatchComponents = namedtuple('MockWatchComponents', ['mock_stream', 'mock_stream_events'])

@pytest.fixture(scope="function")
def mock_watch():
    mock_stream_events = []
    mock_stream = AsyncMock()
    mock_stream.__aiter__.return_value = mock_stream_events

    with patch('kubernetes_asyncio.watch.Watch') as mock_watch:
        mock_watch.return_value.stream.return_value.__aenter__.return_value = mock_stream

        yield MockWatchComponents(
            mock_stream=mock_stream,
            mock_stream_events=mock_stream_events
        )

@pytest.fixture(scope="function")
def sample_pod():
    """Sample kubernetes_asyncio pod object"""
    pod = MagicMock()
    pod.metadata.name = "test-pod"
    pod.metadata.namespace = "default"
    pod.to_dict.return_value = {
        "metadata": {"name": "test-pod", "namespace": "default"},
        "spec": {"containers": [{"name": "test-container"}]}
    }
    return pod

@pytest.fixture(scope="function")
def sample_deployment():
    """Sample kubernetes_asyncio deployment object"""
    deployment = MagicMock()
    deployment.metadata.name = "test-deployment"
    deployment.metadata.namespace = "default"
    deployment.to_dict.return_value = {
        "metadata": {"name": "test-deployment", "namespace": "default"},
        "spec": {"replicas": 3}
    }
    return deployment

@pytest.fixture(scope="function")
def sample_service():
    """Sample kubernetes_asyncio service object"""
    service = MagicMock()
    service.metadata.name = "test-service"
    service.metadata.namespace = "default"
    service.to_dict.return_value = {
        "metadata": {"name": "test-service", "namespace": "default"},
        "spec": {"ports": [{"port": 80}]}
    }
    return service

@pytest.fixture(autouse=True)
def mock_load_k8s_config():
    with patch("kubernetes_asyncio.config.load_incluster_config") as mock_config:
        yield mock_config

@pytest.fixture(autouse=True)
def mock_apps_client():
    mock_client = AsyncMock()
    mock_client.api_client.close = AsyncMock()
    yield mock_client

@pytest.fixture(autouse=True)
def mock_apps_client_class(mock_apps_client):
    with patch('kubernetes_asyncio.client.AppsV1Api') as mock_client:
        mock_client.return_value = mock_apps_client
        yield mock_client

@pytest.fixture(autouse=True)
def mock_core_client():
    mock_client = AsyncMock()
    mock_client.api_client.close = AsyncMock()
    yield mock_client

@pytest.fixture(autouse=True)
def mock_core_client_class(mock_core_client):
    with patch('kubernetes_asyncio.client.CoreV1Api') as mock_client:
        mock_client.return_value = mock_core_client
        yield mock_client

@pytest.fixture(autouse=True)
def mock_batch_client():
    mock_client = AsyncMock()
    mock_client.api_client.close = AsyncMock()
    yield mock_client

@pytest.fixture(autouse=True)
def mock_batch_client_class(mock_batch_client):
    with patch('kubernetes_asyncio.client.BatchV1Api') as mock_client:
        mock_client.return_value = mock_batch_client
        yield mock_client