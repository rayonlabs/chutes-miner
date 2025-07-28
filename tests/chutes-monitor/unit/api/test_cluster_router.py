from chutes_common.constants import CLUSTER_ENDPOINT
import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock
from datetime import datetime, timezone

from chutes_common.monitoring.models import ClusterState, ClusterStatus, HeartbeatData


@pytest.fixture
def test_client():
    """Create test client for router testing"""
    from fastapi import FastAPI
    from chutes_monitor.api.cluster.router import router
    app = FastAPI()
    app.include_router(router, prefix=CLUSTER_ENDPOINT)
    return TestClient(app)


@pytest.mark.asyncio
async def test_register_cluster_success(mock_cluster_monitor, test_client, create_cluster_request_data):
    """Test successful cluster registration via API"""
    mock_cluster_monitor.register_cluster = AsyncMock()
    
    request = create_cluster_request_data()
    json_data = request.model_dump_json()
    response = test_client.post(f"{CLUSTER_ENDPOINT}/test-cluster", data=json_data)
    
    assert response.status_code == 200
    mock_cluster_monitor.register_cluster.assert_called_once()

@pytest.mark.asyncio
async def test_register_cluster_failure(mock_cluster_monitor, test_client, create_cluster_request_data):
    """Test cluster registration failure via API"""
    mock_cluster_monitor.register_cluster = AsyncMock(side_effect=Exception("Registration failed"))
    
    request_data = create_cluster_request_data()
    json_data = request_data.model_dump_json()
    response = test_client.post(f"{CLUSTER_ENDPOINT}/test-cluster", data=json_data)
    
    assert response.status_code == 500


def test_unregister_cluster_success(mock_cluster_monitor, test_client):
    """Test successful cluster unregistration via API"""
    mock_cluster_monitor.delete_cluster = AsyncMock()

    response = test_client.delete(f"{CLUSTER_ENDPOINT}/test-cluster")
    
    assert response.status_code == 200
    json_response = response.json()
    assert json_response["message"] == "Cluster test-cluster unregistered successfully"
    assert json_response["cluster_name"] == "test-cluster"


@pytest.mark.asyncio
async def test_receive_heartbeat_success(mock_redis_client, test_client):
    """Test successful heartbeat reception via API"""
    # Mock cluster status as healthy

    mock_cluster_status = ClusterStatus(
        cluster_name="test-cluster",
        state=ClusterState.ACTIVE,
        last_heartbeat=datetime.now(timezone.utc).isoformat()
    )
    mock_redis_client.get_cluster_status.return_value = mock_cluster_status
    mock_redis_client.update_cluster_status = AsyncMock()
    
    request = HeartbeatData(
        state=ClusterState.ACTIVE,
        cluster_name="test-cluster",
        timestamp=datetime.now(timezone.utc).isoformat()
    )
    json_data = request.model_dump_json()
    response = test_client.put(f"{CLUSTER_ENDPOINT}/test-cluster/health", data=json_data)
    
    assert response.status_code == 200
    json_response = response.json()
    assert json_response["status"] == "success"
    assert json_response["cluster_name"] == "test-cluster"

@pytest.mark.asyncio
async def test_receive_heartbeat_unhealthy_cluster(mock_redis_client, test_client):
    """Test heartbeat reception for unhealthy cluster"""
    # Mock cluster status as unhealthy
    mock_cluster_status = ClusterStatus(
        cluster_name="test-cluster",
        state=ClusterState.UNHEALTHY,
        last_heartbeat=datetime.now(timezone.utc).isoformat(),
        error_message="Connection timeout"
    )
    mock_redis_client.get_cluster_status.return_value = mock_cluster_status

    request = HeartbeatData(
        state=ClusterState.ACTIVE,
        cluster_name="test-cluster",
        timestamp=datetime.now(timezone.utc).isoformat()
    )
    json_data = request.model_dump_json()
    
    response = test_client.put(f"{CLUSTER_ENDPOINT}/test-cluster/health", data=json_data)
    
    assert response.status_code == 409
    json_response = response.json()
    assert "unhealthy state" in json_response["detail"]


@pytest.mark.asyncio
async def test_receive_resource_update_success(mock_redis_client, test_client, test_resource_update_request):
    """Test successful resource update reception via API"""
    mock_redis_client.update_resource = AsyncMock()
    
    json_data = test_resource_update_request.model_dump()
    response = test_client.patch(f"{CLUSTER_ENDPOINT}/test-cluster/resources", json=json_data)
    
    assert response.status_code == 200
    json_response = response.json()
    assert json_response["status"] == "success"
    assert json_response["cluster_name"] == "test-cluster"