from chutes_common.monitoring.models import ClusterState
from chutes_common.k8s import ClusterResources
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from chutes_agent.config import settings

@pytest.mark.asyncio
@patch('kubernetes_asyncio.client.AppsV1Api')
@patch('kubernetes_asyncio.client.CoreV1Api')
@patch('kubernetes_asyncio.config.load_incluster_config')
async def test_complete_monitoring_workflow(
    mock_config, mock_core_v1, mock_apps_v1, mock_client_class, resource_monitor
):
    """Test the complete monitoring workflow from start to finish"""
    # Setup mocks
    mock_client = AsyncMock()
    mock_client_class.return_value = mock_client
    
    monitor = resource_monitor
    
    # Mock collector to return empty resources
    with patch.object(monitor.collector, 'collect_all_resources') as mock_collect:
        mock_collect.return_value = {'pods': [], 'deployments': [], 'services': []}
        
        # Initialize monitor
        await monitor.start("http://test-control-plane")
        
        # Verify client was created and register_cluster was called
        mock_client_class.assert_called_once_with("http://test-control-plane")
        mock_client.register_cluster.assert_called_once()
        
        # Verify kubernetes_asyncio components were initialized
        mock_config.assert_called_once()
        mock_core_v1.assert_called_once()
        mock_apps_v1.assert_called_once()


@pytest.mark.asyncio
@patch('kubernetes_asyncio.config.load_incluster_config', side_effect=Exception("K8s error"))
async def test_error_handling_and_recovery(mock_config, resource_monitor):
    """Test error handling and recovery mechanisms"""
    from chutes_common.monitoring.models import MonitoringState
    
    monitor = resource_monitor
    
    # Test initialization failure
    with pytest.raises(Exception, match="K8s error"):
        await monitor.initialize()
    
    # Verify status remains in appropriate state
    assert monitor.status.state in [MonitoringState.STOPPED, MonitoringState.ERROR]

@pytest.mark.asyncio
async def test_client_collector_integration(mock_sign_request, mock_aiohttp_session):
    """Test integration between client and collector components"""
    from chutes_agent.client import ControlPlaneClient
    from chutes_agent.collector import ResourceCollector
    
    client = ControlPlaneClient("http://test-control-plane")
    collector = ResourceCollector()
    
    # Mock collector to return sample data
    with patch.object(collector, 'collect_all_resources') as mock_collect:
        mock_collect.return_value = ClusterResources()
        
        # Test the integration
        resources = await collector.collect_all_resources()
        await client.register_cluster(resources)
        
        mock_collect.assert_called_once()
        mock_sign_request.assert_called_once()
        mock_aiohttp_session.session.post.assert_called_once()

@pytest.mark.asyncio
@patch('kubernetes_asyncio.client.AppsV1Api')
@patch('kubernetes_asyncio.client.CoreV1Api')
@patch('kubernetes_asyncio.config.load_incluster_config')
@patch.object(settings, 'cluster_name', 'test-cluster')
@patch.object(settings, 'watch_namespaces', ['default'])
async def test_full_startup_sequence(
    mock_config, mock_core_v1, mock_apps_v1, mock_client_class, resource_monitor
):
    """Test the full application startup sequence"""
    
    # Setup mocks
    mock_client = AsyncMock()
    mock_client_class.return_value = mock_client
    
    monitor = resource_monitor
    
    with patch.object(monitor.collector, 'collect_all_resources') as mock_collect:
        mock_collect.return_value = {'pods': [], 'deployments': [], 'services': []}
        
        # Test startup
        await monitor.start("http://test-control-plane")
        
        # Verify initialization occurred
        mock_client_class.assert_called_once()
        mock_client.register_cluster.assert_called_once()

def test_configuration_integration():
    """Test configuration integration across components"""
    from chutes_agent.config import settings
    from chutes_agent.client import ControlPlaneClient
    from chutes_agent.collector import ResourceCollector
    
    # Test that components use settings correctly
    client = ControlPlaneClient("http://test.com")
    collector = ResourceCollector()
    
    # Client should use cluster name from settings
    assert client.cluster_name == settings.cluster_name
    
    # Collector should use namespaces from settings
    assert collector.namespaces == settings.watch_namespaces

def test_api_models_integration():
    """Test API models work with actual data"""
    from chutes_common.monitoring.models import MonitoringStatus, MonitoringState
    from chutes_common.monitoring.requests import StartMonitoringRequest
    
    # Test creating status with realistic data
    status = MonitoringStatus(
        cluster_id="prod-cluster-1",
        state=MonitoringState.RUNNING,
        last_heartbeat="2023-12-01T10:30:00Z"
    )
    
    assert status.cluster_id == "prod-cluster-1"
    assert status.state == MonitoringState.RUNNING
    
    # Test request model
    request = StartMonitoringRequest(
        control_plane_url="https://control.example.com"
    )
    assert request.control_plane_url == "https://control.example.com"

@pytest.mark.asyncio
async def test_error_propagation(mock_client_class, resource_monitor):
    """Test that errors propagate correctly through the system"""
    from chutes_common.monitoring.models import MonitoringState
    
    monitor = resource_monitor
    
    # Test that client errors affect monitor status
    with patch.object(monitor, 'initialize', side_effect=Exception("Client connection failed")):
        try:
            await monitor.start("https://control.example.com")
        except Exception:
            pass
        
        # Status should reflect the error
        assert monitor.status.state == MonitoringState.ERROR
        assert "Client connection failed" in monitor.status.error_message

@pytest.mark.asyncio
@patch('kubernetes_asyncio.client.AppsV1Api')
@patch('kubernetes_asyncio.client.CoreV1Api') 
@patch('kubernetes_asyncio.config.load_incluster_config')
async def test_monitor_restart_functionality(
    mock_config, mock_core_v1, mock_apps_v1, mock_client_class, resource_monitor
):
    """Test monitor restart functionality in integration"""
    from chutes_common.monitoring.models import MonitoringState
    
    # Setup mocks
    mock_client = AsyncMock()
    mock_client_class.return_value = mock_client
    
    monitor = resource_monitor
    monitor.control_plane_client = mock_client
    
    with patch.object(monitor.collector, 'collect_all_resources') as mock_collect:
        mock_collect.return_value = {'pods': [], 'deployments': [], 'services': []}
        
        # Start monitoring
        await monitor.start("http://test-control-plane")
        assert monitor.status.state == MonitoringState.RUNNING
        
        # Test restart functionality
        await monitor._async_restart()
        
        # Verify restart sequence
        mock_client.remove_cluster.assert_called()

@pytest.mark.asyncio 
async def test_signed_request_integration(mock_sign_request, mock_aiohttp_session):
    """Test that signed requests work properly"""
    from chutes_agent.client import ControlPlaneClient
    
    client = ControlPlaneClient("http://test-control-plane")

    # Test heartbeat (simplest signed request)
    await client.send_heartbeat(ClusterState.ACTIVE)
    
    # Verify sign_request was called and session.post was called
    mock_sign_request.assert_called_once()
    mock_aiohttp_session.session.put.assert_called_once()
    
    # Verify the call was made with proper JSON payload
    call_args = mock_aiohttp_session.session.put.call_args
    assert 'data' in call_args.kwargs
    assert call_args.kwargs['data'] == {"signed": "payload"}

@pytest.mark.asyncio
@patch('kubernetes_asyncio.watch.Watch')
@patch('kubernetes_asyncio.client.AppsV1Api')
@patch('kubernetes_asyncio.client.CoreV1Api')
@patch('kubernetes_asyncio.config.load_incluster_config')
async def test_watch_event_handling_integration(
    mock_config, mock_core_v1, mock_apps_v1, mock_watch, mock_client_class, resource_monitor
):
    """Test watch event handling in integration"""
    from chutes_common.k8s import WatchEvent
    
    # Setup mocks
    mock_client = AsyncMock()
    mock_client_class.return_value = mock_client
    
    monitor = resource_monitor
    monitor.control_plane_client = mock_client
    monitor.apps_v1 = AsyncMock()
    monitor.core_v1 = AsyncMock()
    
    # Create a mock watch event
    test_event = WatchEvent(type="ADDED", object=MagicMock())
    
    with patch('chutes_common.k8s.WatchEvent.from_dict', return_value=test_event):
        # Test event handling
        await monitor.handle_resource_event(test_event)
        
        # Verify the event was sent to control plane
        mock_client.send_resource_update.assert_called_once_with(test_event)

@pytest.mark.asyncio
@pytest.mark.parametrize('mock_namespaces', [['test-ns1', 'test-ns2']], indirect=True)
async def test_multi_namespace_integration(mock_namespaces):
    """Test integration with multiple namespaces"""
    from chutes_agent.collector import ResourceCollector
    
    collector = ResourceCollector()
    
    # Setup mocks for K8s API calls
    collector.core_v1 = AsyncMock()
    collector.apps_v1 = AsyncMock()
    
    # Mock responses for each namespace
    mock_response = MagicMock()
    mock_response.items = []
    
    collector.core_v1.list_namespaced_pod.return_value = mock_response
    collector.apps_v1.list_namespaced_deployment.return_value = mock_response
    collector.core_v1.list_namespaced_service.return_value = mock_response
    
    # Test collection
    resources = await collector.collect_all_resources()
    
    # Verify calls were made for both namespaces
    assert collector.core_v1.list_namespaced_pod.call_count == 2
    assert collector.apps_v1.list_namespaced_deployment.call_count == 2
    assert collector.core_v1.list_namespaced_service.call_count == 2