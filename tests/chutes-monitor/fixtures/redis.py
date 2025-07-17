from unittest.mock import AsyncMock, patch

from more_itertools import side_effect
import pytest

@pytest.fixture(scope='module')
def mock_redis_client_instance():
    patches = [
        patch('chutes_monitor.api.main.MonitoringRedisClient'),
        patch('chutes_monitor.api.cluster.router.MonitoringRedisClient'),
        patch('chutes_monitor.cluster_monitor.MonitoringRedisClient'),
    ]
    
    mock_instance = AsyncMock()
    _patches = []
    
    for p in patches:
        mock_class = p.start()
        mock_class.return_value = mock_instance
        _patches.append(p)
    
    yield mock_instance
    
    # Clean up
    for p in _patches:
        p.stop()

@pytest.fixture(scope='function')
def mock_redis_client(mock_redis_client_instance):
    mock_redis_client_instance.reset_mock(side_effect=True)
    yield mock_redis_client_instance