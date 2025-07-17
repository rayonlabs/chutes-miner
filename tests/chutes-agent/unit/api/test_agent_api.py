import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient
from fastapi import FastAPI
from chutes_agent.api.monitor.router import router
from chutes_common.monitoring.models import MonitoringState, MonitoringStatus

# Create test app
app = FastAPI()
app.include_router(router)
client = TestClient(app)

def test_health_check():
    """Test health check endpoint"""
    with patch('chutes_agent.api.monitor.router.settings') as mock_settings:
        mock_settings.cluster_name = "test-cluster"
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "healthy", "cluster": "test-cluster"}

def test_get_status():
    """Test get status endpoint"""
    with patch('chutes_agent.api.monitor.router.resource_monitor') as mock_monitor:
        mock_status = MonitoringStatus(state="running")
        mock_monitor.status = mock_status
        
        response = client.get("/status")
        assert response.status_code == 200
        # Response should contain the status fields

@patch('chutes_agent.api.monitor.router.resource_monitor')
def test_start_monitoring_success(mock_monitor):
    """Test successful start monitoring"""
    mock_monitor.status = MonitoringState.STOPPED
    mock_monitor.stop = AsyncMock()
    mock_monitor.start = AsyncMock()
    
    with patch('chutes_agent.api.monitor.router.settings') as mock_settings:
        mock_settings.cluster_name = "test-cluster"
        
        response = client.post("/start", json={"control_plane_url": "http://test.com"})
        assert response.status_code == 200
        assert "Monitoring started" in response.json()["message"]

@patch('chutes_agent.api.monitor.router.resource_monitor')
def test_start_monitoring_failure(mock_monitor):
    """Test failed start monitoring"""
    mock_monitor.status = MonitoringState.STOPPED
    mock_monitor.stop = AsyncMock()
    mock_monitor.start = AsyncMock(side_effect=Exception("Start failed"))
    
    response = client.post("/start", json={"control_plane_url": "http://test.com"})
    assert response.status_code == 500

@patch('chutes_agent.api.monitor.router.resource_monitor')
def test_stop_monitoring_success(mock_monitor):
    """Test successful stop monitoring"""
    mock_monitor.stop = AsyncMock()
    
    response = client.post("/stop")
    assert response.status_code == 200
    assert response.json() == {"message": "Monitoring stopped"}

@patch('chutes_agent.api.monitor.router.resource_monitor')
def test_stop_monitoring_failure(mock_monitor):
    """Test failed stop monitoring"""
    mock_monitor.stop = AsyncMock(side_effect=Exception("Stop failed"))
    
    response = client.post("/stop")
    assert response.status_code == 500

def test_start_monitoring_invalid_payload():
    """Test start monitoring with invalid payload"""
    response = client.post("/start", json={"invalid_field": "value"})
    assert response.status_code == 422  # Validation error

def test_start_monitoring_missing_url():
    """Test start monitoring with missing URL"""
    response = client.post("/start", json={})
    assert response.status_code == 422  # Validation error