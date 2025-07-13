from chutes_common.monitoring.models import ClusterResources, ClusterState
import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch
import aiohttp
from chutes_agent.config import settings

def test_control_plane_client_init():
    """Test client initialization"""
    from chutes_agent.client import ControlPlaneClient
    client = ControlPlaneClient("http://test-control-plane")
    assert client.base_url == "http://test-control-plane"
    assert client.cluster_name == settings.cluster_name

def test_control_plane_client_init_strips_trailing_slash():
    """Test that trailing slash is stripped from URL"""
    from chutes_agent.client import ControlPlaneClient
    client = ControlPlaneClient("http://test-control-plane/")
    assert client.base_url == "http://test-control-plane"

def test_serialize_k8s_object_with_to_dict(control_plane_client, sample_pod):
    """Test serialization of object with to_dict method"""
    result = control_plane_client._serialize_k8s_object(sample_pod)
    expected = {
        "metadata": {"name": "test-pod", "namespace": "default"},
        "spec": {"containers": [{"name": "test-container"}]}
    }
    assert result == expected

def test_serialize_k8s_object_with_dict(control_plane_client):
    """Test serialization of dict object"""
    obj = MagicMock()
    obj.__dict__ = {"name": "test", "value": 123}
    
    result = control_plane_client._serialize_k8s_object(obj)
    assert result == {"name": "test", "value": 123}

def test_serialize_k8s_object_string_fallback(control_plane_client):
    """Test serialization fallback to string"""
    obj = "simple string"
    result = control_plane_client._serialize_k8s_object(obj)
    assert result == "simple string"

def test_convert_object_dict_recursive(control_plane_client):
    """Test recursive dict conversion"""
    test_dict = {
        "simple": "value",
        "_private": "hidden",
        "nested": {"key": "value"},
        "list": [{"item": "value"}]
    }
    
    result = control_plane_client._convert_object_dict(test_dict)
    
    assert result["simple"] == "value"
    assert "_private" not in result
    assert result["nested"] == {"key": "value"}
    assert result["list"] == [{"item": "value"}]

def test_convert_object_dict_datetime(control_plane_client):
    """Test datetime handling in dict conversion"""
    from datetime import datetime
    dt = datetime(2023, 1, 1, 12, 0, 0)
    test_dict = {"timestamp": dt}
    
    result = control_plane_client._convert_object_dict(test_dict)
    assert result["timestamp"] == dt.isoformat()

@pytest.mark.asyncio
@patch('chutes_agent.client.sign_request')
async def test_send_initial_resources_success(mock_sign, mock_aiohttp_session, control_plane_client, sample_pod, sample_deployment):
    """Test successful initial resources send"""
    # Setup mocks
    mock_sign.return_value = ({"Authorization": "Bearer token"}, {"data": "payload"})

    resources = ClusterResources()

    await control_plane_client.register_cluster(resources)

    # Verify sign_request was called
    mock_sign.assert_called_once()
    # Verify session.post was called
    mock_aiohttp_session.session.post.assert_called_once()

@pytest.mark.asyncio
@patch('chutes_agent.client.sign_request')
async def test_send_initial_resources_failure(mock_sign, mock_aiohttp_session, control_plane_client):
    """Test failed initial resources send"""
    # Setup mocks
    mock_sign.return_value = ({"Authorization": "Bearer token"}, {"data": "payload"})
    mock_aiohttp_session.response.status = 500
    mock_aiohttp_session.response.text = AsyncMock(return_value="Internal Server Error")

    resources = {"pods": []}

    with pytest.raises(Exception, match="Failed to send initial resources: 500"):
        await control_plane_client.register_cluster(resources)

@pytest.mark.asyncio
@patch('chutes_agent.client.sign_request')
async def test_send_resource_update_success(mock_sign, mock_aiohttp_session, control_plane_client, sample_pod):
    """Test successful resource update send"""
    # Setup mocks
    mock_sign.return_value = ({"Authorization": "Bearer token"}, {"data": "payload"})

    resource_data = {
        'event_type': 'ADDED',
        'resource_type': 'Pod',
        'resource': sample_pod
    }

    await control_plane_client.send_resource_update(resource_data)

    # Verify calls were made
    mock_sign.assert_called_once()
    mock_aiohttp_session.session.post.assert_called_once()

@pytest.mark.asyncio
@patch('chutes_agent.client.sign_request')
async def test_send_heartbeat_success(mock_sign, mock_aiohttp_session, control_plane_client):
    """Test successful heartbeat send"""
    # Setup mocks
    mock_sign.return_value = ({"Authorization": "Bearer token"}, {"data": "payload"})

    await control_plane_client.send_heartbeat(ClusterState.ACTIVE)

    # Verify calls were made
    mock_sign.assert_called_once()
    mock_aiohttp_session.session.post.assert_called_once()

@pytest.mark.asyncio
@patch('chutes_agent.client.sign_request')
async def test_send_heartbeat_failure(mock_sign, mock_aiohttp_session, control_plane_client):
    """Test failed heartbeat send"""
    # Setup mocks
    mock_sign.return_value = ({"Authorization": "Bearer token"}, {"data": "payload"})
    mock_aiohttp_session.response.status = 503
    mock_aiohttp_session.response.text = AsyncMock(return_value="Service Unavailable")

    with pytest.raises(Exception, match="Failed to send heartbeat: 503"):
        await control_plane_client.send_heartbeat(ClusterState.ACTIVE)
