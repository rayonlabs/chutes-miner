from chutes_agent.client import ControlPlaneClient
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from chutes_common.monitoring.models import ClusterState, MonitoringState
from chutes_common.k8s import WatchEvent

@pytest.fixture(autouse=True)
def setup(
    mock_load_k8s_config, mock_core_client_class, mock_batch_client_class, 
    mock_apps_client_class
):
    pass

def test_resource_monitor_init(
    mock_core_client, mock_batch_client, mock_apps_client
):
    """Test monitor initialization"""
    from chutes_agent.monitor import ResourceMonitor
    monitor = ResourceMonitor()
    assert monitor.control_plane_client is None
    assert monitor.collector is not None
    assert monitor.core_v1 == mock_core_client
    assert monitor.apps_v1 == mock_apps_client
    assert monitor.batch_v1 == mock_batch_client
    assert monitor._watcher_task is None
    assert monitor._status.state == MonitoringState.STOPPED

def test_resource_monitor_status_property(resource_monitor):
    """Test status property access"""
    status = resource_monitor.status
    assert hasattr(status, 'state')
    assert status.state == MonitoringState.STOPPED

@pytest.mark.asyncio
async def test_start_monitoring(resource_monitor):
    """Test starting monitoring"""
    with patch.object(resource_monitor, '_start_monitoring_tasks') as mock_start:
        with patch.object(resource_monitor, '_register_cluster') as mock_register:
            await resource_monitor.start("http://test-control-plane")
            
            # Verify control plane client was set
            assert resource_monitor.control_plane_client is not None
            mock_start.assert_called_once()
            mock_register.assert_called_once

@pytest.mark.asyncio
async def test_stop_monitoring(resource_monitor):
    """Test stopping monitoring"""
    # Create a mock task
    async def dummy_task():
        while True:
            try:
                await asyncio.sleep(10)
            except asyncio.CancelledError:
                raise
    
    # Start the task and assign it
    mock_task = asyncio.create_task(dummy_task())
    resource_monitor._watcher_task = mock_task
    
    await resource_monitor.stop_monitoring_tasks()
    
    assert mock_task.cancelled()
    assert resource_monitor._watcher_task is None
    assert resource_monitor.state == MonitoringState.STOPPED

@pytest.mark.asyncio
async def test_stop_monitoring_no_task(resource_monitor):
    """Test stopping monitoring when no task exists"""
    resource_monitor._watcher_task = None
    
    # Should not raise exception
    await resource_monitor.stop_monitoring_tasks()
    assert resource_monitor.state == MonitoringState.STOPPED

def test_restart(resource_monitor):
    """Test restart functionality"""
    with patch('asyncio.create_task') as mock_create_task:
        with patch.object(resource_monitor, '_async_restart'):
            resource_monitor.state = MonitoringState.RUNNING
            resource_monitor._restart()
            
            mock_create_task.assert_called_once()
            # Verify the task was created with the right coroutine
            args, kwargs = mock_create_task.call_args
            assert hasattr(args[0], '__await__')  # Check it's a coroutine

@pytest.mark.asyncio
async def test_async_restart(resource_monitor):
    """Test async restart functionality"""
    # Setup mocks
    resource_monitor.control_plane_client = AsyncMock()
    resource_monitor.collector.collect_all_resources = AsyncMock(return_value={})
    resource_monitor._stop_monitoring_tasks = AsyncMock()
    resource_monitor._start_monitoring_tasks = AsyncMock()
    
    await resource_monitor._async_restart()
    
    # Verify sequence of calls
    resource_monitor._stop_monitoring_tasks.assert_called_once()
    resource_monitor.collector.collect_all_resources.assert_called_once()
    resource_monitor.control_plane_client.set_cluster_resources.assert_called_once()
    resource_monitor._start_monitoring_tasks.assert_called_once()

@pytest.mark.asyncio
async def test_initialize_success(
    mock_load_k8s_config, mock_core_client_class, mock_apps_client_class, 
    mock_batch_client_class, resource_monitor
):
    """Test successful initialization"""
    # Setup mocks
    resource_monitor.control_plane_client = AsyncMock()
    resource_monitor.collector.collect_all_resources = AsyncMock(return_value={
        'pods': [], 'deployments': [], 'services': [], 'nodes': []
    })
    
    mock_load_k8s_config.assert_called_once()
    mock_core_client_class.assert_called_once()
    mock_apps_client_class.assert_called_once()
    mock_batch_client_class.assert_called_once()

@pytest.mark.asyncio
async def test_initialize_failure(mock_load_k8s_config, resource_monitor):
    """Test initialization failure"""
    mock_load_k8s_config.side_effect=Exception("Config error")
    with pytest.raises(Exception, match="Config error"):
        await resource_monitor.initialize()

@pytest.mark.asyncio
async def test_handle_resource_event(resource_monitor):
    """Test handling resource events"""
    # Setup
    resource_monitor.control_plane_client = AsyncMock()
    
    event = WatchEvent(
        type="ADDED",
        object=MagicMock()
    )
    
    await resource_monitor.handle_resource_event(event)
    
    resource_monitor.control_plane_client.send_resource_update.assert_called_once_with(event)

@pytest.mark.asyncio
async def test_handle_resource_event_error(resource_monitor):
    """Test handling resource event with error"""
    # Setup
    resource_monitor.control_plane_client = AsyncMock()
    resource_monitor.control_plane_client.send_resource_update.side_effect = Exception("Network error")
    
    event = WatchEvent(
        type="ADDED",
        object=MagicMock()
    )
    
    # Should not raise exception, just log error
    await resource_monitor.handle_resource_event(event)

@pytest.mark.asyncio
@patch('asyncio.sleep', side_effect=[0, asyncio.CancelledError()])
async def test_send_heartbeat(mock_sleep, resource_monitor):
    """Test sending heartbeat"""
    resource_monitor.control_plane_client = AsyncMock()
    
    await resource_monitor.send_heartbeat()
    
    # Should have sent at least one heartbeat
    assert resource_monitor.control_plane_client.send_heartbeat.call_count >= 1

@pytest.mark.asyncio
@patch('asyncio.sleep', side_effect=[0, asyncio.CancelledError()])
async def test_send_heartbeat_error_handling(mock_sleep, resource_monitor):
    """Test heartbeat error handling"""
    resource_monitor.control_plane_client = AsyncMock()
    resource_monitor.control_plane_client.send_heartbeat.side_effect = Exception("Network error")
    resource_monitor._restart = MagicMock()

    # Should continue despite errors
    await resource_monitor.send_heartbeat()

    resource_monitor._restart.assert_called_once()

@pytest.mark.asyncio
async def test_watch_namespaced_deployments_success(resource_monitor, mock_watch):
    """Test watching deployments successfully"""
    # Setup
    resource_monitor.apps_v1 = AsyncMock()
    resource_monitor.handle_resource_event = AsyncMock()
    
    # Mock watch stream
    
    mock_event = {'type': 'ADDED', 'object': MagicMock()}
    mock_watch.mock_stream_events.append(mock_event)

    with patch('chutes_common.k8s.WatchEvent.from_dict') as mock_from_dict:
        mock_watch_event = MagicMock()
        mock_from_dict.return_value = mock_watch_event
        
        # Cancel after processing one event
        resource_monitor.handle_resource_event.side_effect = asyncio.CancelledError()
        
        await resource_monitor.watch_namespaced_deployments("default")
        
        mock_from_dict.assert_called_once_with(mock_event)
        resource_monitor.handle_resource_event.assert_called_once_with(mock_watch_event)

@pytest.mark.asyncio
async def test_watch_namespaced_deployments_error_triggers_restart(resource_monitor, mock_watch):
    """Test that errors in deployment watching trigger restart"""
    # Setup
    resource_monitor.apps_v1 = AsyncMock()
    resource_monitor._restart = MagicMock()
    
    with patch('kubernetes_asyncio.watch.Watch') as mock_watch:
        # Make stream raise an exception
        mock_watch.return_value.stream.side_effect = Exception("Network error")
        
        # This should trigger restart and break the loop
        await resource_monitor.watch_namespaced_deployments("default")
        
        resource_monitor._restart.assert_called_once()

@pytest.mark.asyncio
async def test_watch_namespaced_pods_success(resource_monitor, mock_watch):
    """Test watching pods successfully"""
    # Setup
    resource_monitor.core_v1 = AsyncMock()
    resource_monitor.handle_resource_event = AsyncMock()
    
    # Mock watch stream
    mock_event = {'type': 'MODIFIED', 'object': MagicMock()}
    mock_watch.mock_stream_events.append(mock_event)
    
    with patch('chutes_common.k8s.WatchEvent.from_dict') as mock_from_dict:
        mock_watch_event = MagicMock()
        mock_from_dict.return_value = mock_watch_event
        
        # Cancel after processing one event
        resource_monitor.handle_resource_event.side_effect = asyncio.CancelledError()
        
        await resource_monitor.watch_namespaced_pods("default")
        
        mock_from_dict.assert_called_once_with(mock_event)
        resource_monitor.handle_resource_event.assert_called_once_with(mock_watch_event)

@pytest.mark.asyncio
async def test_watch_namespaced_pods_error_triggers_restart(resource_monitor):
    """Test that errors in pod watching trigger restart"""
    # Setup
    resource_monitor.core_v1 = AsyncMock()
    resource_monitor._restart = MagicMock()
    
    with patch('kubernetes_asyncio.watch.Watch') as mock_watch:
        # Make stream raise an exception
        mock_watch.return_value.stream.side_effect = Exception("Watch error")
        
        # This should trigger restart and break the loop
        await resource_monitor.watch_namespaced_pods("default")
        
        resource_monitor._restart.assert_called_once()

@pytest.mark.asyncio
async def test_watch_namespaced_services_success(resource_monitor, mock_watch):
    """Test watching services successfully"""
    # Setup
    resource_monitor.core_v1 = AsyncMock()
    resource_monitor.handle_resource_event = AsyncMock()
    
    # Mock watch stream
    mock_event = {'type': 'DELETED', 'object': MagicMock()}
    mock_watch.mock_stream_events.append(mock_event)
    
    with patch('chutes_common.k8s.WatchEvent.from_dict') as mock_from_dict:
        mock_watch_event = MagicMock()
        mock_from_dict.return_value = mock_watch_event
        
        # Cancel after processing one event
        resource_monitor.handle_resource_event.side_effect = asyncio.CancelledError()
        
        await resource_monitor.watch_namespaced_services("default")
        
        mock_from_dict.assert_called_once_with(mock_event)
        resource_monitor.handle_resource_event.assert_called_once_with(mock_watch_event)

@pytest.mark.asyncio
async def test_watch_namespaced_services_error_triggers_restart(resource_monitor):
    """Test that errors in service watching trigger restart"""
    # Setup
    resource_monitor.core_v1 = AsyncMock()
    resource_monitor._restart = MagicMock()
    
    with patch('kubernetes_asyncio.watch.Watch') as mock_watch:
        # Make stream raise an exception
        mock_watch.return_value.stream.side_effect = Exception("Service watch error")
        
        # This should trigger restart and break the loop
        await resource_monitor.watch_namespaced_services("default")
        
        resource_monitor._restart.assert_called_once()

@pytest.mark.asyncio
async def test_start_monitoring_success(resource_monitor):
    """Test successful start monitoring flow"""
    # Setup mocks
    resource_monitor.send_heartbeat = AsyncMock()
    resource_monitor._start_watch_resources = AsyncMock()
    
    await resource_monitor._start_monitoring_tasks()
    
    # Verify state transitions
    assert resource_monitor.state == MonitoringState.RUNNING
    assert resource_monitor.status.error_message is None
    resource_monitor.send_heartbeat.assert_called_once()
    assert resource_monitor._watcher_task is not None
    resource_monitor._start_watch_resources.assert_called_once()

# @pytest.mark.asyncio
# async def test_start_monitoring_failure(resource_monitor):
#     """Test start monitoring failure"""
#     # Setup mocks
#     resource_monitor.send_heartbeat = AsyncMock(side_effect=Exception("Heartbeat failed"))
    
#     with pytest.raises(Exception, match="Heartbeat failed"):
#         await resource_monitor._start_monitoring_tasks()
    
#     # Verify error state
#     assert resource_monitor.state == MonitoringState.ERROR
#     assert resource_monitor.status.error_message == "Heartbeat failed"

@pytest.mark.asyncio
async def test_start_monitoring_cancelled(resource_monitor):
    """Test start monitoring when cancelled"""
    # Setup mocks
    resource_monitor.send_hearbeat = AsyncMock()
    
    # Trigger a cancel for the watcher task
    with patch('asyncio.create_task', side_effect=asyncio.CancelledError()):
        try:
            await resource_monitor._start_monitoring_tasks()
        except asyncio.CancelledError:
            pass   
    
    # Verify state when cancelled
    assert resource_monitor.state == MonitoringState.STOPPED

@pytest.mark.asyncio
@pytest.mark.parametrize('mock_namespaces', [['default', 'kube-system']], indirect=True)
async def test_watch_resources_task_creation(mock_namespaces, resource_monitor):
    """Test that _watch_resources creates correct tasks"""
    # Setup
    resource_monitor.watch_namespaced_deployments = AsyncMock()
    resource_monitor.watch_namespaced_pods = AsyncMock()
    resource_monitor.watch_namespaced_services = AsyncMock()
    resource_monitor.watch_namespaced_jobs = AsyncMock()
    resource_monitor.watch_nodes = AsyncMock()
        
    # Make the gather finish quickly
    with patch('asyncio.gather', side_effect=asyncio.CancelledError()):
        try:
            await resource_monitor._start_watch_resources()
        except asyncio.CancelledError:
            pass
    
    # Verify tasks were created for each namespace
    assert resource_monitor.watch_namespaced_deployments.call_count == 2
    assert resource_monitor.watch_namespaced_pods.call_count == 2
    assert resource_monitor.watch_namespaced_services.call_count == 2
    assert resource_monitor.watch_nodes.call_count == 1

@pytest.mark.asyncio
async def test_watch_resources_exception_handling(resource_monitor):
    """Test exception handling in _watch_resources"""
    # Setup
    resource_monitor.watch_namespaced_deployments = AsyncMock()
    resource_monitor.watch_namespaced_pods = AsyncMock()
    resource_monitor.watch_namespaced_services = AsyncMock()
    resource_monitor.watch_nodes = AsyncMock()
    resource_monitor.send_heartbeat = AsyncMock()
    
    # Mock settings
    with patch('chutes_agent.config.settings') as mock_settings:
        mock_settings.watch_namespaces = ['default']
        
        # Make gather raise an exception
        with patch('asyncio.gather', side_effect=Exception("Gather failed")):
            await resource_monitor._start_watch_resources()
    
    # Verify error state is set
    assert resource_monitor._status.state == MonitoringState.ERROR
    assert resource_monitor._status.error_message == "Gather failed"