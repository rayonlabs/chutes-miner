from datetime import datetime
from chutes_common.k8s import WatchEvent, WatchEventType
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

@pytest.mark.asyncio
@patch('chutes_agent.client.sign_request')
async def test_send_initial_resources_success(mock_sign, mock_aiohttp_session, control_plane_client, cluster_resources_with_objects):
    """Test successful initial resources send"""
    # Setup mocks
    mock_sign.return_value = ({"Authorization": "Bearer token"}, {"data": "payload"})

    await control_plane_client.register_cluster(cluster_resources_with_objects)

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

    event = WatchEvent(
        type=WatchEventType.ADDED,
        object=MagicMock()
    )

    await control_plane_client.send_resource_update(event)

    # Verify calls were made
    mock_sign.assert_called_once()
    mock_aiohttp_session.session.put.assert_called_once()

@pytest.mark.asyncio
@patch('chutes_agent.client.sign_request')
async def test_send_heartbeat_success(mock_sign, mock_aiohttp_session, control_plane_client):
    """Test successful heartbeat send"""
    # Setup mocks
    mock_sign.return_value = ({"Authorization": "Bearer token"}, {"data": "payload"})

    await control_plane_client.send_heartbeat(ClusterState.ACTIVE)

    # Verify calls were made
    mock_sign.assert_called_once()
    mock_aiohttp_session.session.put.assert_called_once()

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

def _find_problematic_data(obj, path=""):
    """Recursively find non-JSON-serializable data"""
    if isinstance(obj, dict):
        for key, value in obj.items():
            try:
                json.dumps(value)
            except (TypeError, ValueError) as e:
                print(f"Problem at {path}.{key}: {type(value)} = {repr(value)[:100]}...")
                if isinstance(value, (dict, list)):
                    _find_problematic_data(value, f"{path}.{key}")
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            try:
                json.dumps(item)
            except (TypeError, ValueError) as e:
                print(f"Problem at {path}[{i}]: {type(item)} = {repr(item)[:100]}...")
                if isinstance(item, (dict, list)):
                    _find_problematic_data(item, f"{path}[{i}]")


# def test_cluster_resources_to_dict_basic(cluster_resources_with_objects):
#     """Test basic to_dict conversion"""
#     result = cluster_resources_with_objects.to_dict()
    
#     # Should not raise an exception
#     assert isinstance(result, dict)
#     assert 'pods' in result
#     assert 'deployments' in result
#     assert 'services' in result
#     assert 'nodes' in result


# def test_cluster_resources_json_serializable(cluster_resources_with_objects):
#     """Test that to_dict result is JSON serializable"""
#     result = cluster_resources_with_objects.to_dict()
    
#     # This should not raise an exception
#     json_str = json.dumps(result)
#     assert isinstance(json_str, str)
    
#     # Should be able to deserialize back
#     parsed = json.loads(json_str)
#     assert isinstance(parsed, dict)


@pytest.mark.asyncio
@patch('chutes_agent.client.sign_request')
async def test_register_cluster_success(mock_sign, mock_aiohttp_session, 
                                      control_plane_client, cluster_resources_with_objects):
    """Test successful register_cluster call"""
    # Setup mocks
    mock_sign.return_value = (
        {"Authorization": "Bearer token", "Content-Type": "application/json"},
        {"signed": "payload"}
    )
    
    # This should not raise an exception
    await control_plane_client.register_cluster(cluster_resources_with_objects)
    
    # Verify the calls were made
    mock_sign.assert_called_once()
    mock_aiohttp_session.session.post.assert_called_once()


# def test_manual_serialization_debugging(sample_k8s_objects):
#     """Debug serialization step by step"""
#     pod = sample_k8s_objects['pod']
    
#     # Test individual object serialization
#     pod_dict = pod.to_dict()
#     print(f"Pod dict keys: {pod_dict.keys()}")
    
#     # Test our serialization methods
#     resources = ClusterResources(pods=[pod])
    
#     # Test each step
#     try:
#         result = resources.to_dict()
#         print(f"to_dict succeeded: {type(result)}")
#     except Exception as e:
#         print(f"to_dict failed: {e}")
#         raise
    
#     try:
#         json_str = json.dumps(result)
#         print(f"JSON serialization succeeded: {len(json_str)} characters")
#     except Exception as e:
#         print(f"JSON serialization failed: {e}")
#         # Let's find the problematic data
#         _find_problematic_data(result)
#         raise


@pytest.mark.asyncio
@patch('chutes_agent.client.sign_request')
async def test_register_cluster_payload_inspection(mock_sign, mock_aiohttp_session,
                                                  control_plane_client, cluster_resources_with_objects):
    """Inspect the actual payload being sent"""
    # Capture the payload passed to sign_request
    captured_payload = None
    
    def capture_sign_request(*args, **kwargs):
        nonlocal captured_payload
        captured_payload = args[0] if len(args) == 1 else kwargs.get('payload')
        return (
            {"Authorization": "Bearer token", "Content-Type": "application/json"},
            {"signed": "payload"}
        )
    
    mock_sign.side_effect = capture_sign_request
    
    await control_plane_client.register_cluster(cluster_resources_with_objects)
    
    # Verify we captured the payload
    assert captured_payload is not None
    
    # Try to serialize the captured payload
    try:
        json.dumps(captured_payload)
        print("Payload is JSON serializable")
    except Exception as e:
        print(f"Payload serialization failed: {e}")
        _find_problematic_data(captured_payload, "payload")
        raise


# def test_empty_cluster_resources():
#     """Test with empty cluster resources"""
#     resources = ClusterResources()
#     result = resources.to_dict()
    
#     # Should work fine
#     json_str = json.dumps(result)
#     assert isinstance(json_str, str)


# def test_cluster_resources_field_validation_with_dicts():
#     """Test that field validation works with dict inputs"""
#     # Test with dict inputs instead of actual K8s objects
#     pod_dict = {
#         "metadata": {"name": "dict-pod", "namespace": "default"},
#         "spec": {"containers": [{"name": "test"}]}
#     }
    
#     deployment_dict = {
#         "metadata": {"name": "dict-deployment", "namespace": "default"},
#         "spec": {"replicas": 1}
#     }
    
#     # This should work with the field validation
#     resources = ClusterResources(
#         pods=[pod_dict],
#         deployments=[deployment_dict]
#     )
    
#     assert len(resources.pods) == 1
#     assert len(resources.deployments) == 1


@pytest.mark.asyncio
@patch('chutes_agent.client.sign_request')
async def test_register_cluster_error_handling(mock_sign, mock_aiohttp_session, control_plane_client):
    """Test error handling in register_cluster"""
    # Setup mocks
    mock_sign.return_value = (
        {"Authorization": "Bearer token", "Content-Type": "application/json"},
        {"signed": "payload"}
    )
    mock_aiohttp_session.response.status = 500
    mock_aiohttp_session.response.text = AsyncMock(return_value="Internal Server Error")
    
    resources = ClusterResources()
    
    # Should raise an exception for 500 status
    with pytest.raises(Exception, match="Failed to send initial resources: 500"):
        await control_plane_client.register_cluster(resources)