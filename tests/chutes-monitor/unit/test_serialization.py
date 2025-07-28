from chutes_common.monitoring.requests import SetClusterResourcesRequest
from kubernetes_asyncio.client import V1Deployment, V1ObjectMeta
import pytest

@pytest.mark.asyncio
async def test_register_cluster_serialization(create_cluster_request_data):
    """Test successful cluster registration via API"""
    
    request = create_cluster_request_data()
    json_data = request.model_dump()
    
    request = SetClusterResourcesRequest(**json_data)

    assert len(request.resources.deployments) == 1

    assert type(request.resources.deployments[0]) == V1Deployment
    assert type(request.resources.deployments[0].metadata) == V1ObjectMeta