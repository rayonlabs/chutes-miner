from unittest.mock import AsyncMock, PropertyMock, patch
import pytest


@pytest.fixture(autouse=True, scope='module')
def mock_authorize():
    with patch("chutes_common.auth.authorize") as mock_authorize:
        mock_authorize.return_value = lambda: None
        yield mock_authorize

@pytest.fixture
def mock_cluster_monitor():
    from chutes_monitor.api.cluster.router import ClusterRouter
    with patch.object(ClusterRouter, 'cluster_monitor', new_callable=PropertyMock) as mock_clister_monitor_property:
        mock_cluster_monitor = AsyncMock()
        mock_clister_monitor_property.return_value = mock_cluster_monitor

        yield mock_cluster_monitor