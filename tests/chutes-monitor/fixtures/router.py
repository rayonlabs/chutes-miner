from unittest.mock import AsyncMock, PropertyMock, patch

from chutes_monitor.api.cluster.router import ClusterRouter
import pytest

# @pytest.fixture
# def mock_redis_client():
#     with patch.object(ClusterRouter, 'redis_client', new_callable=PropertyMock) as mock_client_property:
#         mock_redis_client = AsyncMock()
#         mock_client_property.return_value = mock_redis_client

#         yield mock_redis_client

@pytest.fixture
def mock_cluster_monitor():
    with patch.object(ClusterRouter, 'cluster_monitor', new_callable=PropertyMock) as mock_clister_monitor_property:
        mock_cluster_monitor = AsyncMock()
        mock_clister_monitor_property.return_value = mock_cluster_monitor

        yield mock_cluster_monitor