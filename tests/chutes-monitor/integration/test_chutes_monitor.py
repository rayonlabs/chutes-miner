import pytest
import asyncio
from unittest.mock import AsyncMock, patch
from datetime import datetime, timezone, timedelta

from chutes_monitor.cluster_monitor import HealthChecker, ClusterMonitor
from chutes_common.monitoring.models import ClusterStatus, ClusterState, ClusterResources


@pytest.mark.asyncio
async def test_health_checker_integration(mock_redis_client):
    """Integration test for health checker with real async behavior"""
    with patch('chutes_monitor.cluster_monitor.settings') as mock_settings:
        
        mock_settings.heartbeat_interval = 1  # Short interval for testing
        
        # Create cluster with stale heartbeat
        stale_time = datetime.now(timezone.utc) - timedelta(minutes=5)
        cluster_status = ClusterStatus(
            cluster_name="test-cluster",
            state=ClusterState.ACTIVE,
            last_heartbeat=stale_time.isoformat(),
            error_message=None
        )
        
        mock_redis_client.get_all_cluster_statuses.return_value = [cluster_status]
        
        health_checker = HealthChecker()
        
        # Start health checker
        health_checker.start()
        
        # Wait for at least one check cycle
        await asyncio.sleep(1.5)
        
        # Stop health checker
        await health_checker.stop()
        
        # Verify Redis calls were made
        mock_redis_client.get_all_cluster_statuses.assert_called()


@pytest.mark.asyncio
async def test_cluster_monitor_full_lifecycle(mock_redis_client):
    """Integration test for complete cluster lifecycle"""
    with patch('chutes_monitor.cluster_monitor.HealthChecker') as mock_health_checker_class, \
         patch('chutes_monitor.cluster_monitor.settings') as mock_settings:
        
        mock_settings.url = "http://test-control-plane:8000"
        mock_health_checker_instance = AsyncMock()
        mock_health_checker_class.return_value = mock_health_checker_instance
        
        # Test complete lifecycle
        cluster_monitor = ClusterMonitor()
        
        # Register cluster
        cluster_name = "integration-test-cluster"
        resources = ClusterResources()
        await cluster_monitor.register_cluster(cluster_name, resources)
        
        # Verify registration
        mock_redis_client.track_cluster.assert_called_once_with(cluster_name, resources)
        
        # List clusters
        mock_cluster_status = ClusterStatus(
            cluster_name=cluster_name,
            state=ClusterState.ACTIVE,
            last_heartbeat=datetime.now(timezone.utc).isoformat(),
            error_message=None
        )
        mock_redis_client.get_all_cluster_names.return_value = [cluster_name]
        mock_redis_client.get_cluster_status.return_value = mock_cluster_status
        
        clusters = await cluster_monitor.list_clusters()
        assert len(clusters) == 1
        assert clusters[0].cluster_name == cluster_name
        
        # Delete cluster
        await cluster_monitor.delete_cluster(cluster_name)
        mock_redis_client.clear_cluster.assert_called_once_with(cluster_name)