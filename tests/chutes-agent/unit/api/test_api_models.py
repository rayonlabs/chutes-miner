import pytest
from chutes_agent.api.monitor.models import MonitoringState, MonitoringStatus, StartMonitoringRequest

def test_monitoring_state_enum():
    """Test MonitoringState enum values"""
    assert MonitoringState.STOPPED == "stopped"
    assert MonitoringState.STARTING == "starting"
    assert MonitoringState.RUNNING == "running"
    assert MonitoringState.ERROR == "error"

def test_start_monitoring_request():
    """Test StartMonitoringRequest model"""
    request = StartMonitoringRequest(control_plane_url="http://test.com")
    assert request.control_plane_url == "http://test.com"

def test_start_monitoring_request_validation():
    """Test StartMonitoringRequest validation"""
    # Should work with valid URL
    request = StartMonitoringRequest(control_plane_url="https://api.example.com")
    assert request.control_plane_url == "https://api.example.com"

def test_monitoring_status_defaults():
    """Test MonitoringStatus model defaults"""
    status = MonitoringStatus(state="stopped")
    assert status.cluster_id is None
    assert status.state == "stopped"
    assert status.error_message is None
    assert status.last_heartbeat is None

def test_monitoring_status_with_values():
    """Test MonitoringStatus model with values"""
    status = MonitoringStatus(
        cluster_id="test-cluster",
        control_plane_url="http://test.com",
        state="running",
        error_message=None,
        last_heartbeat="2023-01-01T12:00:00Z"
    )
    assert status.cluster_id == "test-cluster"
    assert status.state == "running"
    assert status.last_heartbeat == "2023-01-01T12:00:00Z"

def test_monitoring_status_with_error():
    """Test MonitoringStatus with error state"""
    status = MonitoringStatus(
        state="error",
        error_message="Connection failed"
    )
    assert status.state == "error"
    assert status.error_message == "Connection failed"