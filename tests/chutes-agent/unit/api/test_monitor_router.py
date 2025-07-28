# test_api_monitor_router.py
from unittest.mock import MagicMock, patch, AsyncMock
from fastapi.testclient import TestClient
from fastapi import FastAPI
from chutes_common.monitoring.models import MonitoringState, MonitoringStatus
import pytest

# Health Check Endpoint Tests

# @pytest.fixture(autouse=True, scope='module')
# def mock_monitor_instance():
#     mock_monitor = MagicMock()
#     mock_monitor.start = AsyncMock()
#     mock_monitor.stop = AsyncMock()
#     yield mock_monitor

# # Create test app
# @pytest.fixture(autouse=True, scope="module")
# def mock_monitor_class(mock_monitor_instance, mock_authorize):
#     with patch('chutes_agent.monitor.ResourceMonitor') as mock_class:
#         mock_class.return_value = mock_monitor_instance
#         yield mock_class

@pytest.fixture(autouse=True)
def mock_monitor(resource_monitor):
    with patch('chutes_agent.api.monitor.router.resource_monitor', resource_monitor):
        yield resource_monitor

@pytest.fixture(autouse=True)
def app(resource_monitor):
    from chutes_agent.api.monitor.router import router
    # Create test app
    app = FastAPI()
    app.include_router(router)
    yield app

@pytest.fixture
def client(app):
    client = TestClient(app)
    yield client

@patch('chutes_agent.api.monitor.router.settings')
def test_health_check_success(mock_settings, client):
    """Test successful health check"""
    mock_settings.cluster_name = "test-cluster"
    
    response = client.get("/health")
    
    assert response.status_code == 200
    assert response.json() == {"status": "healthy", "cluster": "test-cluster"}

@patch('chutes_agent.api.monitor.router.settings')
def test_health_check_different_cluster(mock_settings, client):
    """Test health check with different cluster name"""
    mock_settings.cluster_name = "production-cluster-1"
    
    response = client.get("/health")
    
    assert response.status_code == 200
    assert response.json() == {"status": "healthy", "cluster": "production-cluster-1"}

def test_health_check_endpoint_structure(app):
    """Test that health check endpoint is properly registered"""
    routes = [route.path for route in app.routes]
    assert "/health" in routes
    
    # Check that it's a GET endpoint
    health_route = next(route for route in app.routes if route.path == "/health")
    assert "GET" in health_route.methods

# Status Endpoint Tests

def test_get_status_stopped(resource_monitor, client):
    """Test get status when monitoring is stopped"""
    resource_monitor.state = MonitoringState.STOPPED
    
    response = client.get("/status")
    
    assert response.status_code == 200
    response_data = response.json()
    assert response_data["state"] == "stopped"
    assert response_data["cluster_id"] is None

def test_get_status_running(resource_monitor, client):
    """Test get status when monitoring is running"""
    mock_status = MonitoringStatus(
        state=MonitoringState.RUNNING,
        cluster_id="test-cluster",
        control_plane_url="http://control-plane.example.com",
        error_message=None,
        last_heartbeat="2023-12-01T10:30:00Z"
    )
    resource_monitor._status = mock_status
    
    response = client.get("/status")
    
    assert response.status_code == 200
    response_data = response.json()
    assert response_data["state"] == "running"
    assert response_data["cluster_id"] == "test-cluster"
    assert response_data["last_heartbeat"] == "2023-12-01T10:30:00Z"

def test_get_status_error(resource_monitor, client):
    """Test get status when monitoring is in error state"""
    mock_status = MonitoringStatus(
        state=MonitoringState.ERROR,
        cluster_id="test-cluster",
        control_plane_url="http://control-plane.example.com",
        error_message="Connection timeout"
    )
    resource_monitor._status = mock_status
    
    response = client.get("/status")
    
    assert response.status_code == 200
    response_data = response.json()
    assert response_data["state"] == "error"
    assert response_data["error_message"] == "Connection timeout"

def test_get_status_starting(resource_monitor, client):
    """Test get status when monitoring is starting"""
    mock_status = MonitoringStatus(
        state=MonitoringState.STARTING,
        cluster_id="test-cluster",
        control_plane_url="http://control-plane.example.com"
    )
    resource_monitor._status = mock_status
    
    response = client.get("/status")
    
    assert response.status_code == 200
    response_data = response.json()
    assert response_data["state"] == "starting"

# Start Monitoring Endpoint Tests

@patch('chutes_agent.api.monitor.router.settings')
def test_start_monitoring_success_when_stopped(mock_settings, resource_monitor, client):
    """Test successful start monitoring when currently stopped"""
    mock_settings.cluster_name = "test-cluster"
    resource_monitor._status = MonitoringStatus(state=MonitoringState.STOPPED)
    resource_monitor.start = AsyncMock()
    
    request_data = {"control_plane_url": "http://control-plane.example.com"}
    response = client.post("/start", json=request_data)
    
    assert response.status_code == 200
    response_data = response.json()
    assert response_data["message"] == "Monitoring started"
    assert response_data["cluster"] == "test-cluster"
    resource_monitor.start.assert_called_once_with("http://control-plane.example.com")

@patch('chutes_agent.api.monitor.router.settings')
def test_start_monitoring_failure_when_running(mock_settings, resource_monitor, client):
    """Test successful start monitoring when already running (restarts)"""
    mock_settings.cluster_name = "test-cluster"
    resource_monitor._status = MonitoringStatus(state=MonitoringState.RUNNING)

    resource_monitor.stop = AsyncMock()
    resource_monitor.start = AsyncMock()
    
    request_data = {"control_plane_url": "http://new-control-plane.example.com"}
    response = client.post("/start", json=request_data)
    
    assert response.status_code == 409
    response_data = response.json()
    assert response_data["detail"] == "Monitoring process already running."
    
    # Should not interfer with existing process
    resource_monitor.stop.assert_not_called()
    resource_monitor.start.assert_not_called()

def test_start_monitoring_invalid_payload(resource_monitor, client):
    """Test start monitoring with invalid payload"""
    request_data = {"invalid_field": "value"}
    resource_monitor.stop = AsyncMock()
    resource_monitor.start = AsyncMock()

    response = client.post("/start", json=request_data)
    
    assert response.status_code == 422  # Validation error
    
    # Should not call start method
    resource_monitor.start.assert_not_called()

def test_start_monitoring_missing_url(resource_monitor, client):
    """Test start monitoring with missing control_plane_url"""
    resource_monitor.stop = AsyncMock()
    resource_monitor.start = AsyncMock()
    
    request_data = {}
    response = client.post("/start", json=request_data)
    
    assert response.status_code == 422  # Validation error
    
    # Should not call start method
    resource_monitor.start.assert_not_called()

@patch('chutes_agent.api.monitor.router.settings')
def test_start_monitoring_failure(mock_settings, resource_monitor, client):
    """Test start monitoring failure"""
    mock_settings.cluster_name = "test-cluster"
    resource_monitor._status = MonitoringStatus(state=MonitoringState.STOPPED)
    resource_monitor.start = AsyncMock(side_effect=Exception("Connection failed"))
    
    request_data = {"control_plane_url": "http://control-plane.example.com"}
    response = client.post("/start", json=request_data)
    
    assert response.status_code == 500
    response_data = response.json()
    assert "Connection failed" in response_data["detail"]

def test_start_monitoring_url_validation(client):
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
                mock_monitor.status = MonitoringStatus(state=MonitoringState.STOPPED)
                mock_monitor.start = AsyncMock()
                
                request_data = {"control_plane_url": url}
                response = client.post("/start", json=request_data)
                
                assert response.status_code == 200
                mock_monitor.start.assert_called_once_with(url)

# Stop Monitoring Endpoint Tests

def test_stop_monitoring_success(resource_monitor, client):
    """Test successful stop monitoring"""
    resource_monitor.stop = AsyncMock()
    
    response = client.get("/stop")
    
    assert response.status_code == 200
    response_data = response.json()
    assert response_data["message"] == "Monitoring stopped"
    resource_monitor.stop.assert_called_once()

def test_stop_monitoring_failure(resource_monitor, client):
    """Test stop monitoring failure"""
    resource_monitor.stop = AsyncMock(side_effect=Exception("Stop operation failed"))
    
    response = client.get("/stop")
    
    assert response.status_code == 500
    response_data = response.json()
    assert "Stop operation failed" in response_data["detail"]

def test_stop_monitoring_when_already_stopped(resource_monitor, client):
    """Test stop monitoring when already stopped (should still succeed)"""
    resource_monitor.stop = AsyncMock()
    
    response = client.get("/stop")
    
    assert response.status_code == 200
    response_data = response.json()
    assert response_data["message"] == "Monitoring stopped"
    resource_monitor.stop.assert_called_once()

# Integration and Edge Case Tests

def test_all_endpoints_registered(app):
    """Test that all expected endpoints are registered"""
    routes = [route.path for route in app.routes]
    expected_routes = ["/health", "/status", "/start", "/stop"]
    
    for route in expected_routes:
        assert route in routes

def test_endpoint_methods(app):
    """Test that endpoints use correct HTTP methods"""
    route_methods = {route.path: route.methods for route in app.routes}
    
    assert "GET" in route_methods["/health"]
    assert "GET" in route_methods["/status"] 
    assert "POST" in route_methods["/start"]
    assert "GET" in route_methods["/stop"]

@patch('chutes_agent.api.monitor.router.settings')
def test_monitoring_workflow_integration(mock_settings, resource_monitor, client):
    """Test complete monitoring workflow: health -> start -> status -> stop"""
    mock_settings.cluster_name = "integration-test-cluster"
    
    # Initially stopped
    resource_monitor._status = MonitoringStatus(state=MonitoringState.STOPPED)
    resource_monitor.start = AsyncMock()
    resource_monitor.stop = AsyncMock()
    
    # 1. Check health
    health_response = client.get("/health")
    assert health_response.status_code == 200
    assert health_response.json()["status"] == "healthy"
    
    # 2. Start monitoring
    start_response = client.post("/start", json={"control_plane_url": "http://test.com"})
    assert start_response.status_code == 200
    resource_monitor.start.assert_called_once_with("http://test.com")
    
    # 3. Check status (simulate running state)
    resource_monitor._status = MonitoringStatus(
        state=MonitoringState.RUNNING,
        control_plane_url="http://test.com"
    )
    status_response = client.get("/status")
    assert status_response.status_code == 200
    assert status_response.json()["state"] == "running"
    
    # 4. Stop monitoring
    stop_response = client.get("/stop")
    assert stop_response.status_code == 200
    resource_monitor.stop.assert_called_once()

def test_concurrent_start_requests(resource_monitor, client):
    """Test handling of concurrent start requests"""
    resource_monitor._status = MonitoringStatus(state=MonitoringState.STOPPED)
    resource_monitor.start = AsyncMock()
    
    # Simulate multiple concurrent requests
    request_data = {"control_plane_url": "http://control-plane.example.com"}
    
    responses = []
    for _ in range(3):
        response = client.post("/start", json=request_data)
        responses.append(response)
    
    # All should succeed (though in practice, you might want different behavior)
    for response in responses:
        assert response.status_code == 200

def test_request_validation_edge_cases(resource_monitor, client):
    """Test request validation with various edge cases"""
    resource_monitor._status = MonitoringStatus(state=MonitoringState.STOPPED)
    
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
def test_start_monitoring_logs_errors(mock_logger, resource_monitor, client):
    """Test that start monitoring logs errors appropriately"""
    resource_monitor._status = MonitoringStatus(state=MonitoringState.STOPPED)
    resource_monitor.start = AsyncMock(side_effect=Exception("Test error"))
    
    request_data = {"control_plane_url": "http://control-plane.example.com"}
    response = client.post("/start", json=request_data)
    
    assert response.status_code == 500
    mock_logger.error.assert_called_once()
    
    # Check that the error message was logged
    log_call_args = mock_logger.error.call_args[0][0]
    assert "Failed to start monitoring" in log_call_args
    assert "Test error" in log_call_args

@patch('chutes_agent.api.monitor.router.logger')
def test_stop_monitoring_logs_errors(mock_logger, resource_monitor, client):
    """Test that stop monitoring logs errors appropriately"""
    resource_monitor.stop = AsyncMock(side_effect=Exception("Stop error"))
    
    response = client.get("/stop")
    
    assert response.status_code == 500
    mock_logger.error.assert_called_once()
    
    # Check that the error message was logged
    log_call_args = mock_logger.error.call_args[0][0]
    assert "Failed to stop monitoring" in log_call_args
    assert "Stop error" in log_call_args

# Performance and Resource Tests

def test_health_check_performance(client):
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

def test_status_endpoint_no_side_effects(resource_monitor, client):
    """Test that status endpoint doesn't modify state"""
    initial_status = MonitoringStatus(state=MonitoringState.RUNNING)
    resource_monitor._status = initial_status
    
    # Call status endpoint multiple times
    for _ in range(5):
        response = client.get("/status")
        assert response.status_code == 200
    
    # Status should remain unchanged
    assert resource_monitor.status == initial_status