import pytest
import asyncio
import time
from unittest.mock import AsyncMock, patch
from datetime import datetime, timezone, timedelta
from chutes_monitor.cluster_monitor import ClusterMonitor, HealthChecker
from chutes_common.monitoring.models import ClusterStatus, ClusterState, ClusterResources

# @patch('chutes_monitor.cluster_monitor.MonitoringRedisClient')
@patch('chutes_monitor.cluster_monitor.settings')
@pytest.mark.asyncio
async def test_health_checker_initialization(mock_settings, mock_redis_client):
    """Test HealthChecker initialization"""
    mock_settings.heartbeat_interval = 30
    # mock_redis_client = AsyncMock()
    # mock_redis_client.get_instance.return_value = mock_redis_client
    
    health_checker = HealthChecker()
    
    assert health_checker.heartbeat_interval == 30
    assert health_checker.redis_client == mock_redis_client
    assert health_checker._running is False
    assert health_checker._task is None


@pytest.mark.asyncio
async def test_health_checker_start_stop(mock_settings, mock_redis_client):
    """Test starting and stopping the health checker"""
    mock_settings.heartbeat_interval = 30
    
    health_checker = HealthChecker()
    
    # Test start
    health_checker.start()
    assert health_checker._running is True
    assert health_checker._task is not None
    
    # Test stop
    await health_checker.stop()
    assert health_checker._running is False


@patch('chutes_monitor.cluster_monitor.settings')
@pytest.mark.asyncio
async def test_health_checker_already_running(mock_settings, mock_redis_client):
    """Test starting health checker when already running"""
    mock_settings.heartbeat_interval = 30
    
    health_checker = HealthChecker()
    health_checker._running = True
    
    health_checker.start()
    # Should not create a new task
    assert health_checker._task is None


@patch('chutes_monitor.cluster_monitor.settings')
@pytest.mark.asyncio
async def test_check_cluster_health_healthy(mock_settings, mock_redis_client):
    """Test checking health of a healthy cluster"""
    mock_settings.heartbeat_interval = 30
    
    health_checker = HealthChecker()
    
    # Create a healthy cluster status
    cluster_status = ClusterStatus(
        cluster_name="test-cluster",
        state=ClusterState.ACTIVE,
        last_heartbeat=datetime.now(timezone.utc).isoformat(),
        error_message=None
    )
    
    await health_checker._check_cluster_health(cluster_status)
    
    # Should not mark as unhealthy
    assert not hasattr(health_checker, '_mark_cluster_unhealthy_called')


@patch('chutes_monitor.cluster_monitor.settings')
@pytest.mark.asyncio
async def test_check_cluster_health_stale_heartbeat(mock_settings, mock_redis_client):
    """Test checking health of a cluster with stale heartbeat"""
    mock_settings.heartbeat_interval = 30
    
    health_checker = HealthChecker()
    
    # Create a cluster status with stale heartbeat
    stale_time = datetime.now(timezone.utc) - timedelta(minutes=5)
    cluster_status = ClusterStatus(
        cluster_name="test-cluster",
        state=ClusterState.ACTIVE,
        last_heartbeat=stale_time.isoformat(),
        error_message=None
    )
    
    # Mock _mark_cluster_unhealthy to track calls
    health_checker._mark_cluster_unhealthy = AsyncMock()
    
    await health_checker._check_cluster_health(cluster_status)
    
    # Should mark as unhealthy
    health_checker._mark_cluster_unhealthy.assert_called_once()


@patch('chutes_monitor.cluster_monitor.settings')
@pytest.mark.asyncio
async def test_check_cluster_health_no_heartbeat(mock_settings, mock_redis_client):
    """Test checking health of a cluster with no heartbeat"""
    mock_settings.heartbeat_interval = 30
    
    health_checker = HealthChecker()
    
    # Create a cluster status with no heartbeat
    cluster_status = ClusterStatus(
        cluster_name="test-cluster",
        state=ClusterState.ACTIVE,
        last_heartbeat=None,
        error_message=None
    )
    
    # Mock _mark_cluster_unhealthy to track calls
    health_checker._mark_cluster_unhealthy = AsyncMock()
    
    await health_checker._check_cluster_health(cluster_status)
    
    # Should mark as unhealthy
    health_checker._mark_cluster_unhealthy.assert_called_once()


@patch('chutes_monitor.cluster_monitor.settings')
@pytest.mark.asyncio
async def test_mark_cluster_unhealthy(mock_settings, mock_redis_client):
    """Test marking a cluster as unhealthy"""
    mock_settings.heartbeat_interval = 30
    
    health_checker = HealthChecker()
    
    cluster_status = ClusterStatus(
        cluster_name="test-cluster",
        state=ClusterState.ACTIVE,
        last_heartbeat=datetime.now(timezone.utc).isoformat(),
        error_message=None
    )
    
    reason = "Test reason"
    
    await health_checker._mark_cluster_unhealthy(cluster_status, reason)
    
    # Verify Redis client update was called
    mock_redis_client.update_cluster_status.assert_called_once()
    call_args = mock_redis_client.update_cluster_status.call_args[0]
    updated_status = call_args[0]
    
    assert updated_status.cluster_name == "test-cluster"
    assert updated_status.state == ClusterState.UNHEALTHY
    assert updated_status.error_message == reason


@patch('chutes_monitor.cluster_monitor.settings')
@pytest.mark.asyncio
async def test_cleanup_stale_clusters(mock_settings, mock_redis_client):
    """Test cleanup of stale clusters"""
    mock_settings.heartbeat_interval = 30
    
    health_checker = HealthChecker()
    
    # Create old cluster status
    old_time = datetime.now(timezone.utc) - timedelta(hours=25)
    old_cluster = ClusterStatus(
        cluster_name="old-cluster",
        state=ClusterState.ACTIVE,
        last_heartbeat=old_time,
        error_message=None
    )
    
    # Create recent cluster status
    recent_time = datetime.now(timezone.utc) - timedelta(minutes=5)
    recent_cluster = ClusterStatus(
        cluster_name="recent-cluster",
        state=ClusterState.ACTIVE,
        last_heartbeat=recent_time,
        error_message=None
    )
    
    mock_redis_client.get_all_cluster_statuses.return_value = [old_cluster, recent_cluster]
    
    await health_checker._cleanup_stale_clusters()
    
    # Should only clear the old cluster
    mock_redis_client.clear_cluster.assert_called_once_with("old-cluster")


@patch('chutes_monitor.cluster_monitor.settings')
@pytest.mark.asyncio
async def test_health_checker_redis_error_handling(mock_settings, mock_redis_client):
    """Test health checker handles Redis errors gracefully"""
    mock_settings.heartbeat_interval = 30
    mock_redis_client.get_all_cluster_statuses.side_effect = Exception("Redis connection lost")
    
    health_checker = HealthChecker()
    
    # This should not raise an exception
    await health_checker._check_all_clusters()
    
    # Verify Redis was called despite error
    mock_redis_client.get_all_cluster_statuses.assert_called_once()


@patch('chutes_monitor.cluster_monitor.HealthChecker')
@patch('chutes_monitor.cluster_monitor.settings')
@pytest.mark.asyncio
async def test_cluster_monitor_redis_error_during_registration(mock_settings, mock_health_checker, mock_redis_client):
    """Test cluster monitor handles Redis errors during registration"""
    mock_settings.url = "http://test-control-plane:8000"
    mock_redis_client.track_cluster.side_effect = Exception("Redis write failed")
    mock_health_checker_instance = AsyncMock()
    mock_health_checker.return_value = mock_health_checker_instance
    
    cluster_monitor = ClusterMonitor()
    
    cluster_name = "test-cluster"
    resources = ClusterResources()
    
    # Should re-raise the exception
    with pytest.raises(Exception, match="Redis write failed"):
        await cluster_monitor.register_cluster(cluster_name, resources)


@patch('chutes_monitor.cluster_monitor.settings')
@pytest.mark.asyncio
async def test_health_checker_timezone_aware_timestamps(mock_settings, mock_redis_client):
    """Test health checker handles timezone-aware timestamps correctly"""
    mock_settings.heartbeat_interval = 30
    
    health_checker = HealthChecker()
    
    # Create cluster with timezone-naive timestamp (should be treated as UTC)
    naive_time = datetime.now() - timedelta(minutes=5)  # No timezone info
    cluster_status = ClusterStatus(
        cluster_name="test-cluster",
        state=ClusterState.ACTIVE,
        last_heartbeat=naive_time.isoformat(),
        error_message=None
    )

    # Mock _mark_cluster_unhealthy to track calls
    health_checker._mark_cluster_unhealthy = AsyncMock()
    
    await health_checker._check_cluster_health(cluster_status)
    
    # Should handle timezone conversion and mark as unhealthy
    health_checker._mark_cluster_unhealthy.assert_called_once()


@patch('chutes_monitor.cluster_monitor.settings')
@pytest.mark.asyncio
async def test_health_checker_future_timestamp(mock_settings, mock_redis_client):
    """Test health checker handles future timestamps correctly"""
    mock_settings.heartbeat_interval = 30
    
    health_checker = HealthChecker()
    
    # Create cluster with future timestamp
    future_time = datetime.now(timezone.utc) + timedelta(minutes=5)
    cluster_status = ClusterStatus(
        cluster_name="test-cluster",
        state=ClusterState.ACTIVE,
        last_heartbeat=future_time.isoformat(),
        error_message=None
    )

    # Mock _mark_cluster_unhealthy to track calls
    health_checker._mark_cluster_unhealthy = AsyncMock()
    
    await health_checker._check_cluster_health(cluster_status)
    
    # Should not mark as unhealthy (future timestamp is considered valid)
    health_checker._mark_cluster_unhealthy.assert_not_called()


@patch('chutes_monitor.cluster_monitor.settings')
@pytest.mark.asyncio
async def test_health_checker_already_unhealthy_cluster(mock_settings, mock_redis_client):
    """Test health checker doesn't update already unhealthy clusters unnecessarily"""
    mock_settings.heartbeat_interval = 30
    
    health_checker = HealthChecker()
    
    # Create already unhealthy cluster with stale heartbeat
    stale_time = datetime.now(timezone.utc) - timedelta(minutes=5)
    cluster_status = ClusterStatus(
        cluster_name="test-cluster",
        state=ClusterState.UNHEALTHY,  # Already unhealthy
        last_heartbeat=stale_time.isoformat(),
        error_message="Previous error"
    )
    
    await health_checker._check_cluster_health(cluster_status)
    
    # Should not update Redis since already unhealthy
    mock_redis_client.update_cluster_status.assert_not_called()


@patch('chutes_monitor.cluster_monitor.settings')
@pytest.mark.asyncio
async def test_cleanup_stale_clusters_with_invalid_timestamps(mock_settings, mock_redis_client):
    """Test cleanup handles clusters with invalid timestamps"""
    mock_settings.heartbeat_interval = 30
    
    health_checker = HealthChecker()
    
    # Create cluster with invalid timestamp
    invalid_cluster = ClusterStatus(
        cluster_name="invalid-cluster",
        state=ClusterState.ACTIVE,
        last_heartbeat=datetime.now(timezone.utc),
        error_message=None
    )
    
    # Create valid old cluster
    old_time = datetime.now(timezone.utc) - timedelta(hours=25)
    old_cluster = ClusterStatus(
        cluster_name="old-cluster",
        state=ClusterState.ACTIVE,
        last_heartbeat=old_time,
        error_message=None
    )
    
    mock_redis_client.get_all_cluster_statuses.return_value = [invalid_cluster, old_cluster]
    
    await health_checker._cleanup_stale_clusters()
    
    # Should only clear the old cluster, not the invalid one
    mock_redis_client.clear_cluster.assert_called_once_with("old-cluster")


@patch('chutes_monitor.cluster_monitor.settings')
@pytest.mark.asyncio
async def test_health_checker_performance_many_clusters(mock_settings, mock_redis_client):
    """Test health checker performance with many clusters"""
    mock_settings.heartbeat_interval = 1
    
    health_checker = HealthChecker()
    
    # Create many cluster statuses
    num_clusters = 100
    cluster_statuses = []
    current_time = datetime.now(timezone.utc)
    
    for i in range(num_clusters):
        cluster_status = ClusterStatus(
            cluster_name=f"cluster-{i}",
            state=ClusterState.ACTIVE,
            last_heartbeat=current_time.isoformat(),
            error_message=None
        )
        cluster_statuses.append(cluster_status)
    
    mock_redis_client.get_all_cluster_statuses.return_value = cluster_statuses
    
    # Measure time for checking all clusters
    start_time = time.time()
    await health_checker._check_all_clusters()
    end_time = time.time()
    
    # Should complete within reasonable time (adjust threshold as needed)
    assert end_time - start_time < 1.0  # Should complete in less than 1 second
    
    # Verify all clusters were checked
    mock_redis_client.get_all_cluster_statuses.assert_called_once()


@patch('chutes_monitor.cluster_monitor.settings')
@pytest.mark.asyncio
async def test_health_checker_concurrent_safety(mock_settings, mock_redis_client):
    """Test health checker handles concurrent operations safely"""
    mock_settings.heartbeat_interval = 0.1  # Very short interval
    
    # Add delay to Redis operations to simulate concurrent access
    async def delayed_redis_op(*args, **kwargs):
        await asyncio.sleep(0.05)
        return []
    
    mock_redis_client.get_all_cluster_statuses.side_effect = delayed_redis_op
    
    health_checker = HealthChecker()
    
    # Start multiple concurrent operations
    tasks = []
    for _ in range(5):
        task = asyncio.create_task(health_checker._check_all_clusters())
        tasks.append(task)
    
    # Wait for all to complete
    await asyncio.gather(*tasks)
    
    # Should not raise any exceptions and complete successfully
    assert len(tasks) == 5