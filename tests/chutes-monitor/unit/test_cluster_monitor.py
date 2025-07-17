import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient


@patch('chutes_monitor.api.main.MonitoringRedisClient')
@patch('chutes_monitor.api.main.HealthChecker')
@pytest.mark.asyncio
async def test_lifespan_startup_and_shutdown(mock_health_checker_class, mock_redis_class):
    """Test application lifespan startup and shutdown"""
    mock_redis_client = AsyncMock()
    mock_redis_class.return_value = mock_redis_client

    mock_health_checker = AsyncMock()
    mock_health_checker_class.return_value = mock_health_checker
    
    # Import here to avoid issues with patching
    from chutes_monitor.api.main import lifespan
    from fastapi import FastAPI
    
    app = FastAPI()
    
    # Test lifespan context manager
    async with lifespan(app):
        # During startup
        mock_redis_class.assert_called_once()
        mock_health_checker_class.assert_called_once()
    
    # After shutdown
    mock_health_checker.stop.assert_called_once()
    mock_redis_client.close.assert_called_once()


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