import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient

# Note: Import from your actual main module path
# from chutes_monitor.api.main import app

def test_health_check_endpoint():
    """Test health check endpoint"""
    from chutes_monitor.api.main import app
    
    client = TestClient(app)
    response = client.get("/health")
    
    assert response.status_code == 200
    json_response = response.json()
    assert json_response["status"] == "healthy"
    assert json_response["service"] == "agent-monitor"


def test_ping_endpoint():
    """Test ping endpoint"""
    from chutes_monitor.api.main import app
    
    client = TestClient(app)
    response = client.get("/ping")
    
    assert response.status_code == 200
    json_response = response.json()
    assert json_response["message"] == "pong"


@patch('chutes_monitor.api.main.hashlib')
def test_request_body_checksum_middleware(mock_hashlib):
    """Test request body checksum middleware"""
    from chutes_monitor.api.main import app
    
    mock_hash = MagicMock()
    mock_hash.hexdigest.return_value = "test-checksum"
    mock_hashlib.sha256.return_value = mock_hash
    
    client = TestClient(app)
    
    # Test POST request (should calculate checksum)
    response = client.post("/health", json={"test": "data"})
    mock_hashlib.sha256.assert_called()
    
    # Reset mock
    mock_hashlib.reset_mock()
    
    # Test GET request (should not calculate checksum)
    response = client.get("/health")
    mock_hashlib.sha256.assert_not_called()