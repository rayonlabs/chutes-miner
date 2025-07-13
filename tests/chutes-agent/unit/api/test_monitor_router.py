# test_api_monitor_router.py
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient
from fastapi import FastAPI
from chutes_agent.api.monitor.router import router
from chutes_common.monitoring.models import MonitoringState, MonitoringStatus

# Create test app
app = FastAPI()
app.include_router(router)
client = TestClient(app)

# Health Check Endpoint Tests

@patch('chutes_agent.api.monitor.router.settings')
def test_health_check_success(mock_settings):
    """Test successful health check"""
    mock_settings.cluster_name = "test-cluster"
    
    response = client.get("/health")
    
    assert response.status_code == 200
    assert response.json() == {"status": "healthy", "cluster": "test-cluster"}

@patch('chutes_agent.api.monitor.router.settings')
def test_health_check_different_cluster(mock_settings):
    """Test health check with different cluster name"""
    mock_settings.cluster_name = "production-cluster-1"
    
    response = client.get("/health")
    
    assert response.status_code == 200
    assert response.json() == {"status": "healthy", "cluster": "production-cluster-1"}

def test_health_check_endpoint_structure():
    """Test that health check endpoint is properly registered"""
    routes = [route.path for route in app.routes]
    assert "/health" in routes
    
    # Check that it's a GET endpoint
    health_route = next(route for route in app.routes if route.path == "/health")
    assert "GET" in health_route.methods

# Status Endpoint Tests

@patch('chutes_agent.api.monitor.router.resource_monitor')
def test_get_status_stopped(mock_monitor):
    """Test get status when monitoring is stopped"""
    mock_status = MonitoringStatus(
        state=MonitoringState.STOPPED,
        cluster_id=None,
        control_plane_url=None,
        error_message=None
    )
    mock_monitor.status = mock_status
    
    response = client.get("/status")
    
    assert response.status_code == 200
    response_data = response.json()
    assert response_data["state"] == "stopped"
    assert response_data["cluster_id"] is None

@patch('chutes_agent.api.monitor.router.resource_monitor')
def test_get_status_running(mock_monitor):
    """Test get status when monitoring is running"""
    mock_status = MonitoringStatus(
        state=MonitoringState.RUNNING,
        cluster_id="test-cluster",
        control_plane_url="http://control-plane.example.com",
        error_message=None,
        last_heartbeat="2023-12-01T10:30:00Z"
    )
    mock_monitor.status = mock_status
    
    response = client.get("/status")
    
    assert response.status_code == 200
    response_data = response.json()
    assert response_data["state"] == "running"
    assert response_data["cluster_id"] == "test-cluster"
    assert response_data["last_heartbeat"] == "2023-12-01T10:30:00Z"

@patch('chutes_agent.api.monitor.router.resource_monitor')
def test_get_status_error(mock_monitor):
    """Test get status when monitoring is in error state"""
    mock_status = MonitoringStatus(
        state=MonitoringState.ERROR,
        cluster_id="test-cluster",
        control_plane_url="http://control-plane.example.com",
        error_message="Connection timeout"
    )
    mock_monitor.status = mock_status
    
    response = client.get("/status")
    
    assert response.status_code == 200
    response_data = response.json()
    assert response_data["state"] == "error"
    assert response_data["error_message"] == "Connection timeout"

@patch('chutes_agent.api.monitor.router.resource_monitor')
def test_get_status_starting(mock_monitor):
    """Test get status when monitoring is starting"""
    mock_status = MonitoringStatus(
        state=MonitoringState.STARTING,
        cluster_id="test-cluster",
        control_plane_url="http://control-plane.example.com"
    )
    mock_monitor.status = mock_status
    
    response = client.get("/status")
    
    assert response.status_code == 200
    response_data = response.json()
    assert response_data["state"] == "starting"

# Start Monitoring Endpoint Tests

@patch('chutes_agent.api.monitor.router.settings')
@patch('chutes_agent.api.monitor.router.resource_monitor')
def test_start_monitoring_success_when_stopped(mock_monitor, mock_settings):
    """Test successful start monitoring when currently stopped"""
    mock_settings.cluster_name = "test-cluster"
    mock_monitor.status = MonitoringState.STOPPED
    mock_monitor.start = AsyncMock()
    
    request_data = {"control_plane_url": "http://control-plane.example.com"}
    response = client.post("/start", json=request_data)
    
    assert response.status_code == 200
    response_data = response.json()
    assert response_data["message"] == "Monitoring started"
    assert response_data["cluster"] == "test-cluster"
    mock_monitor.start.assert_called_once_with("http://control-plane.example.com")

@patch('chutes_agent.api.monitor.router.settings')
@patch('chutes_agent.api.monitor.router.resource_monitor')
def test_start_monitoring_success_when_running(mock_monitor, mock_settings):
    """Test successful start monitoring when already running (restarts)"""
    mock_settings.cluster_name = "test-cluster"
    mock_monitor.status = MonitoringState.RUNNING
    mock_monitor.stop = AsyncMock()
    mock_monitor.start = AsyncMock()
    
    request_data = {"control_plane_url": "http://new-control-plane.example.com"}
    response = client.post("/start", json=request_data)
    
    assert response.status_code == 200
    response_data = response.json()
    assert response_data["message"] == "Monitoring started"
    assert response_data["cluster"] == "test-cluster"
    
    # Should stop existing monitoring first, then start new
    mock_monitor.stop.assert_called_once()
    mock_monitor.start.assert_called_once_with("http://new-control-plane.example.com")

@patch('chutes_agent.api.monitor.router.resource_monitor')
def test_start_monitoring_invalid_payload(mock_monitor):
    """Test start monitoring with invalid payload"""
    request_data = {"invalid_field": "value"}
    response = client.post("/start", json=request_data)
    
    assert response.status_code == 422  # Validation error
    
    # Should not call start method
    mock_monitor.start.assert_not_called()

@patch('chutes_agent.api.monitor.router.resource_monitor')
def test_start_monitoring_missing_url(mock_monitor):
    """Test start monitoring with missing control_plane_url"""
    request_data = {}
    response = client.post("/start", json=request_data)
    
    assert response.status_code == 422  # Validation error
    
    # Should not call start method
    mock_monitor.start.assert_not_called()

@patch('chutes_agent.api.monitor.router.settings')
@patch('chutes_agent.api.monitor.router.resource_monitor')
def test_start_monitoring_failure(mock_monitor, mock_settings):
    """Test start monitoring failure"""
    mock_settings.cluster_name = "test-cluster"
    mock_monitor.status = MonitoringState.STOPPED
    mock_monitor.start = AsyncMock(side_effect=Exception("Connection failed"))
    
    request_data = {"control_plane_url": "http://control-plane.example.com"}
    response = client.post("/start", json=request_data)
    
    assert response.status_code == 500
    response_data = response.json()
    assert "Connection failed" in response_data["detail"]

@patch('chutes_agent.api.monitor.router.settings')
@patch('chutes_agent.api.monitor.router.resource_monitor')
def test_start_monitoring_stop_failure(mock_monitor, mock_settings):
    """Test start monitoring when stop fails"""
    mock_settings.cluster_name = "test-cluster"
    mock_monitor.status = MonitoringState.RUNNING
    mock_monitor.stop = AsyncMock(side_effect=Exception("Stop failed"))
    mock_monitor.start = AsyncMock()
    
    request_data = {"control_plane_url": "http://control-plane.example.com"}
    response = client.post("/start", json=request_data)
    
    assert response.status_code == 500
    response_data = response.json()
    assert "Stop failed" in response_data["detail"]

def test_start_monitoring_url_validation():
    """Test start monitoring with various URL formats"""
    valid_urls = [
        "http://localhost:8080",
        "https://api.example.com",
        "http://192.168.1.100:9000",
        "https://control-plane.k8s.local"
    ]
    
    for url in valid_urls:
        with patch('chutes_agent.api.monitor.router.resource_monitor') as mock_monitor:
            with patch('chutes_agent.api.monitor.router.settings') as mock_settings:
                mock_settings.cluster_name = "test-cluster"
                mock_monitor.status = MonitoringState.STOPPED
                mock_monitor.start = AsyncMock()
                
                request_data = {"control_plane_url": url}
                response = client.post("/start", json=request_data)
                
                assert response.status_code == 200
                mock_monitor.start.assert_called_once_with(url)

# Stop Monitoring Endpoint Tests

@patch('chutes_agent.api.monitor.router.resource_monitor')
def test_stop_monitoring_success(mock_monitor):
    """Test successful stop monitoring"""
    mock_monitor.stop = AsyncMock()
    
    response = client.post("/stop")
    
    assert response.status_code == 200
    response_data = response.json()
    assert response_data["message"] == "Monitoring stopped"
    mock_monitor.stop.assert_called_once()

@patch('chutes_agent.api.monitor.router.resource_monitor')
def test_stop_monitoring_failure(mock_monitor):
    """Test stop monitoring failure"""
    mock_monitor.stop = AsyncMock(side_effect=Exception("Stop operation failed"))
    
    response = client.post("/stop")
    
    assert response.status_code == 500
    response_data = response.json()
    assert "Stop operation failed" in response_data["detail"]

@patch('chutes_agent.api.monitor.router.resource_monitor')
def test_stop_monitoring_when_already_stopped(mock_monitor):
    """Test stop monitoring when already stopped (should still succeed)"""
    mock_monitor.stop = AsyncMock()
    
    response = client.post("/stop")
    
    assert response.status_code == 200
    response_data = response.json()
    assert response_data["message"] == "Monitoring stopped"
    mock_monitor.stop.assert_called_once()

# Integration and Edge Case Tests

def test_all_endpoints_registered():
    """Test that all expected endpoints are registered"""
    routes = [route.path for route in app.routes]
    expected_routes = ["/health", "/status", "/start", "/stop"]
    
    for route in expected_routes:
        assert route in routes

def test_endpoint_methods():
    """Test that endpoints use correct HTTP methods"""
    route_methods = {route.path: route.methods for route in app.routes}
    
    assert "GET" in route_methods["/health"]
    assert "GET" in route_methods["/status"] 
    assert "POST" in route_methods["/start"]
    assert "POST" in route_methods["/stop"]

@patch('chutes_agent.api.monitor.router.settings')
@patch('chutes_agent.api.monitor.router.resource_monitor')
def test_monitoring_workflow_integration(mock_monitor, mock_settings):
    """Test complete monitoring workflow: health -> start -> status -> stop"""
    mock_settings.cluster_name = "integration-test-cluster"
    
    # Initially stopped
    mock_monitor.status = MonitoringState.STOPPED
    mock_monitor.start = AsyncMock()
    mock_monitor.stop = AsyncMock()
    
    # 1. Check health
    health_response = client.get("/health")
    assert health_response.status_code == 200
    assert health_response.json()["status"] == "healthy"
    
    # 2. Start monitoring
    start_response = client.post("/start", json={"control_plane_url": "http://test.com"})
    assert start_response.status_code == 200
    mock_monitor.start.assert_called_once_with("http://test.com")
    
    # 3. Check status (simulate running state)
    mock_monitor.status = MonitoringStatus(
        state=MonitoringState.RUNNING,
        control_plane_url="http://test.com"
    )
    status_response = client.get("/status")
    assert status_response.status_code == 200
    assert status_response.json()["state"] == "running"
    
    # 4. Stop monitoring
    stop_response = client.post("/stop")
    assert stop_response.status_code == 200
    mock_monitor.stop.assert_called_once()

@patch('chutes_agent.api.monitor.router.resource_monitor')
def test_concurrent_start_requests(mock_monitor):
    """Test handling of concurrent start requests"""
    mock_monitor.status = MonitoringState.STOPPED
    mock_monitor.start = AsyncMock()
    
    # Simulate multiple concurrent requests
    request_data = {"control_plane_url": "http://control-plane.example.com"}
    
    responses = []
    for _ in range(3):
        response = client.post("/start", json=request_data)
        responses.append(response)
    
    # All should succeed (though in practice, you might want different behavior)
    for response in responses:
        assert response.status_code == 200

@patch('chutes_agent.api.monitor.router.resource_monitor')
def test_request_validation_edge_cases(mock_monitor):
    """Test request validation with various edge cases"""
    mock_monitor.status = MonitoringState.STOPPED
    
    # Test with None URL
    response = client.post("/start", json={"control_plane_url": None})
    assert response.status_code == 422
    
    # Test with empty string URL
    response = client.post("/start", json={"control_plane_url": ""})
    assert response.status_code == 422
    
    # Test with non-string URL
    response = client.post("/start", json={"control_plane_url": 12345})
    assert response.status_code == 422

# Error Handling and Logging Tests

@patch('chutes_agent.api.monitor.router.logger')
@patch('chutes_agent.api.monitor.router.resource_monitor')
def test_start_monitoring_logs_errors(mock_monitor, mock_logger):
    """Test that start monitoring logs errors appropriately"""
    mock_monitor.status = MonitoringState.STOPPED
    mock_monitor.start = AsyncMock(side_effect=Exception("Test error"))
    
    request_data = {"control_plane_url": "http://control-plane.example.com"}
    response = client.post("/start", json=request_data)
    
    assert response.status_code == 500
    mock_logger.error.assert_called_once()
    
    # Check that the error message was logged
    log_call_args = mock_logger.error.call_args[0][0]
    assert "Failed to start monitoring" in log_call_args
    assert "Test error" in log_call_args

@patch('chutes_agent.api.monitor.router.logger')
@patch('chutes_agent.api.monitor.router.resource_monitor')
def test_stop_monitoring_logs_errors(mock_monitor, mock_logger):
    """Test that stop monitoring logs errors appropriately"""
    mock_monitor.stop = AsyncMock(side_effect=Exception("Stop error"))
    
    response = client.post("/stop")
    
    assert response.status_code == 500
    mock_logger.error.assert_called_once()
    
    # Check that the error message was logged
    log_call_args = mock_logger.error.call_args[0][0]
    assert "Failed to stop monitoring" in log_call_args
    assert "Stop error" in log_call_args

@patch('chutes_agent.api.monitor.router.logger')
@patch('chutes_agent.api.monitor.router.resource_monitor')
def test_restart_monitoring_logs_info(mock_monitor, mock_logger):
    """Test that restarting monitoring logs info message"""
    mock_monitor.status = MonitoringState.RUNNING
    mock_monitor.stop = AsyncMock()
    mock_monitor.start = AsyncMock()
    
    request_data = {"control_plane_url": "http://control-plane.example.com"}
    response = client.post("/start", json=request_data)
    
    assert response.status_code == 200
    mock_logger.info.assert_called_once_with("Stopping existing monitoring task")

# Performance and Resource Tests

def test_health_check_performance():
    """Test that health check is fast and doesn't consume resources"""
    import time
    
    with patch('chutes_agent.api.monitor.router.settings') as mock_settings:
        mock_settings.cluster_name = "perf-test-cluster"
        
        start_time = time.time()
        response = client.get("/health")
        end_time = time.time()
        
        assert response.status_code == 200
        # Health check should be very fast (< 100ms in tests)
        assert (end_time - start_time) < 0.1

@patch('chutes_agent.api.monitor.router.resource_monitor')
def test_status_endpoint_no_side_effects(mock_monitor):
    """Test that status endpoint doesn't modify state"""
    initial_status = MonitoringStatus(state=MonitoringState.RUNNING)
    mock_monitor.status = initial_status
    
    # Call status endpoint multiple times
    for _ in range(5):
        response = client.get("/status")
        assert response.status_code == 200
    
    # Status should remain unchanged
    assert mock_monitor.status == initial_status