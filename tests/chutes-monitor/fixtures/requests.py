from chutes_common.k8s import WatchEvent, WatchEventType
from chutes_common.k8s import ClusterResources
from chutes_common.monitoring.requests import RegisterClusterRequest, ResourceUpdateRequest
from kubernetes_asyncio.client import V1Deployment, V1ObjectMeta, V1DeploymentSpec
import pytest

@pytest.fixture
def test_resource_update_request():
    deployment = V1Deployment(
        api_version="apps/v1",
        kind="Deployment",
        metadata=V1ObjectMeta(
            name="test-deployment",
            namespace="default"
        ),
        spec=V1DeploymentSpec(
            replicas=3,
            selector={"matchLabels": {"app": "test-app"}},
            template={
                "metadata": {"labels": {"app": "test-app"}},
                "spec": {
                    "containers": [{
                        "name": "test-container",
                        "image": "nginx:latest"
                    }]
                }
            }
        )
    )

    update_event = WatchEvent(type=WatchEventType.ADDED, object=deployment)
    return ResourceUpdateRequest(event=update_event)

@pytest.fixture
def sample_register_request(sample_k8s_objects):
    """Create ClusterResources with sample objects"""
    return RegisterClusterRequest(
        clsuter_name="test-cluster",
        initial_resources = ClusterResources(
            pods=[sample_k8s_objects['pod']],
            deployments=[sample_k8s_objects['deployment']],
            services=[sample_k8s_objects['service']],
            nodes=[sample_k8s_objects['node']]
        )
    )