import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient
from fastapi import FastAPI
from chutes_common.monitoring.models import MonitoringState, MonitoringStatus

@pytest.fixture(autouse=True, scope='module')
def mock_monitor_instance():
    mock_monitor = MagicMock()
    mock_monitor.start = AsyncMock()
    mock_monitor.stop = AsyncMock()
    mock_monitor.state = MonitoringState.RUNNING
    yield mock_monitor

# Create test app
@pytest.fixture(autouse=True, scope="module")
def mock_monitor_class(mock_monitor_instance, mock_authorize):
    with patch('chutes_agent.monitor.ResourceMonitor') as mock_class:
        mock_class.return_value = mock_monitor_instance
        yield mock_class

@pytest.fixture(autouse=True, scope='module')
def app(mock_monitor_class):
    from chutes_agent.api.monitor.router import router
    # Create test app
    app = FastAPI()
    app.include_router(router)
    yield app

@pytest.fixture
def mock_monitor(mock_monitor_instance):
    mock_monitor_instance.reset_mock(side_effect=True)
    mock_monitor_instance.state = MonitoringState.RUNNING
    yield mock_monitor_instance

@pytest.fixture
def client(app):
    client = TestClient(app)
    yield client

def test_health_check(client):
    """Test health check endpoint"""
    with patch('chutes_agent.api.monitor.router.settings') as mock_settings:
        mock_settings.cluster_name = "test-cluster"
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "healthy", "cluster": "test-cluster"}

def test_get_status(mock_monitor, client):
    """Test get status endpoint"""
    mock_status = MonitoringStatus(state=MonitoringState.RUNNING)
    mock_monitor.status = mock_status
    
    response = client.get("/status")
    assert response.status_code == 200
    # Response should contain the status fields

def test_start_monitoring_success(mock_monitor, client):
    """Test successful start monitoring"""
    mock_monitor.state = state=MonitoringState.STOPPED
    
    with patch('chutes_agent.api.monitor.router.settings') as mock_settings:
        mock_settings.cluster_name = "test-cluster"
        
        response = client.post("/start", json={"control_plane_url": "http://test.com"})
        assert response.status_code == 200
        assert "Monitoring started" in response.json()["message"]

def test_start_monitoring_failure(mock_monitor, client):
    """Test failed start monitoring"""
    mock_monitor.state = state=MonitoringState.STOPPED
    mock_monitor.stop = AsyncMock()
    mock_monitor.start = AsyncMock(side_effect=Exception("Start failed"))
    
    response = client.post("/start", json={"control_plane_url": "http://test.com"})
    assert response.status_code == 500

def test_stop_monitoring_success(mock_monitor, client):
    """Test successful stop monitoring"""
    response = client.get("/stop")
    assert response.status_code == 200
    assert response.json() == {"message": "Monitoring stopped"}

def test_stop_monitoring_failure(mock_monitor, client):
    """Test failed stop monitoring"""
    mock_monitor.stop = AsyncMock(side_effect=Exception("Stop failed"))
    
    response = client.get("/stop")
    assert response.status_code == 500

def test_start_monitoring_invalid_payload(client):
    """Test start monitoring with invalid payload"""
    response = client.post("/start", json={"invalid_field": "value"})
    assert response.status_code == 422  # Validation error

def test_start_monitoring_missing_url(client):
    """Test start monitoring with missing URL"""
    response = client.post("/start", json={})
    assert response.status_code == 422  # Validation error