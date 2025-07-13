import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from chutes_agent.config import settings

@pytest.mark.asyncio
@patch('kubernetes.client.AppsV1Api')
@patch('kubernetes.client.CoreV1Api')
@patch('chutes_agent.collector.config')
async def test_initialize_clients(mock_config, mock_core_v1, mock_apps_v1, resource_collector):
    """Test client initialization"""
    resource_collector.initialize_clients()
    
    assert resource_collector.core_v1 is not None
    assert resource_collector.apps_v1 is not None
    mock_core_v1.assert_called_once()
    mock_apps_v1.assert_called_once()

@pytest.mark.asyncio
@pytest.mark.parametrize('mock_namespaces', [['default', 'test-ns']], indirect=True)
async def test_collect_all_resources_success(mock_namespaces, resource_collector, sample_pod, sample_deployment, sample_service):
    """Test successful resource collection"""
    # Setup mocks
    resource_collector.core_v1 = AsyncMock()
    resource_collector.apps_v1 = AsyncMock()
    
    # Mock responses
    pods_response = MagicMock()
    pods_response.items = [sample_pod]
    deployments_response = MagicMock()
    deployments_response.items = [sample_deployment]
    services_response = MagicMock()
    services_response.items = [sample_service]
    
    resource_collector.core_v1.list_namespaced_pod.return_value = pods_response
    resource_collector.apps_v1.list_namespaced_deployment.return_value = deployments_response
    resource_collector.core_v1.list_namespaced_service.return_value = services_response
    
    resources = await resource_collector.collect_all_resources()
    
    # Should have 2 of each (one from each namespace)
    assert len(resources.deployments) == 2
    assert len(resources.pods) == 2
    assert len(resources.services) == 2

@pytest.mark.asyncio
@pytest.mark.parametrize('mock_namespaces', [['default', 'restricted-ns']], indirect=True)
async def test_collect_all_resources_namespace_error(mock_namespaces, resource_collector, sample_pod):
    """Test resource collection with namespace error"""
    # Setup mocks
    resource_collector.core_v1 = AsyncMock()
    resource_collector.apps_v1 = AsyncMock()
    
    # Mock one namespace to fail
    pods_response = MagicMock()
    pods_response.items = [sample_pod]
    
    resource_collector.core_v1.list_namespaced_pod.side_effect = [
        pods_response,  # First call succeeds
        Exception("Permission denied")  # Second call fails
    ]
    resource_collector.apps_v1.list_namespaced_deployment.side_effect = [
        MagicMock(items=[]),
        Exception("Permission denied")
    ]
    resource_collector.core_v1.list_namespaced_service.side_effect = [
        MagicMock(items=[]),
        Exception("Permission denied")
    ]
    
    resources = await resource_collector.collect_all_resources()
    
    # Should still return resources from successful namespace
    assert len(resources.pods) == 1
    assert len(resources.deployments) == 0
    assert len(resources.services) == 0

@pytest.mark.asyncio
async def test_collect_all_resources_auto_initialize(resource_collector):
    """Test auto-initialization of clients"""
    assert resource_collector.core_v1 is None
    
    with patch('chutes_agent.collector.ResourceCollector.initialize_clients') as mock_init:
        def _mock_clients():
            resource_collector.core_v1 = AsyncMock()
            resource_collector.apps_v1 = AsyncMock()
        mock_init.side_effect = _mock_clients
        await resource_collector.collect_all_resources()
    
    mock_init.assert_called_once()

@pytest.mark.asyncio
async def test_collect_all_resources_empty_namespaces(resource_collector):
    """Test collection with empty namespaces list"""
    # Setup mocks
    resource_collector.core_v1 = AsyncMock()
    resource_collector.apps_v1 = AsyncMock()
    
    resources = await resource_collector.collect_all_resources()
    
    # Should return empty collections
    assert resources.deployments == []
    assert resources.pods == []
    assert resources.services == []
    assert resources.nodes == []