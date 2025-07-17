
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any
import os

from chutes_common.monitoring.models import ClusterStatus, ClusterState, ClusterResources, HeartbeatData
from chutes_common.monitoring.requests import RegisterClusterRequest, ResourceUpdateRequest
from chutes_monitor.cluster_monitor import HealthChecker, ClusterMonitor
from chutes_monitor.config import settings


@pytest.fixture
def mock_settings():
    """Mock settings for testing"""
    with patch('chutes_monitor.cluster_monitor.settings') as mock_settings:
        mock_settings.heartbeat_interval = 30
        mock_settings.url = "http://test-control-plane:8000"
        yield mock_settings


# @pytest.fixture
# def mock_redis_client():
#     """Mock Redis client for testing"""
#     with patch.object(ClusterMonitor, 'redis_client') as mock_client_property:
#         mock_redis_client = AsyncMock()
#         mock_client_property.return_value = mock_redis_client

#         yield mock_redis_client


@pytest.fixture
def sample_cluster_status():
    """Sample cluster status for testing"""
    return ClusterStatus(
        cluster_name="test-cluster",
        state=ClusterState.ACTIVE,
        last_heartbeat=datetime.now(timezone.utc).isoformat(),
        error_message=None
    )


@pytest.fixture
def sample_heartbeat_data():
    """Sample heartbeat data for testing"""
    return HeartbeatData(
        status=ClusterState.ACTIVE,
        timestamp=datetime.now(timezone.utc).isoformat()
    )


@pytest.fixture
def health_checker_with_mocks(mock_redis_client, mock_settings):
    """Health checker with mocked dependencies"""
    with patch('chutes_monitor.cluster_monitor.MonitoringRedisClient') as mock_redis_class:
        mock_redis_class.get_instance.return_value = mock_redis_client
        health_checker = HealthChecker()
        return health_checker


@pytest.fixture
def cluster_monitor_with_mocks(mock_redis_client, mock_settings):
    """Cluster monitor with mocked dependencies"""
    with patch('chutes_monitor.cluster_monitor.MonitoringRedisClient') as mock_redis_class, \
         patch('chutes_monitor.cluster_monitor.HealthChecker') as mock_health_checker:
        mock_redis_class.get_instance.return_value = mock_redis_client
        mock_health_checker.return_value = AsyncMock()
        cluster_monitor = ClusterMonitor()
        return cluster_monitor