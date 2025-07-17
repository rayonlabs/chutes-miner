# test_redis_client.py
import json
from chutes_common.k8s import WatchEvent
from chutes_common.settings import RedisSettings
import pytest
from unittest.mock import AsyncMock, Mock, patch
from datetime import datetime, timezone
from redis import Redis

from chutes_common.monitoring.models import ClusterState, ClusterStatus, ResourceType
from chutes_common.redis import MonitoringRedisClient

settings = RedisSettings()

@pytest.fixture
def mock_redis():
    """Mock Redis client"""
    with patch('chutes_common.redis.Redis') as mock_redis_class:
        mock_redis_instance = Mock(spec=Redis)
        mock_redis_class.from_url.return_value = mock_redis_instance
        yield mock_redis_instance


@pytest.fixture
def redis_client(mock_redis):
    """Create MonitoringRedisClient instance with mocked dependencies"""
    # Reset singleton instance
    MonitoringRedisClient._instance = None
    client = MonitoringRedisClient(settings)
    return client


@pytest.fixture
def sample_cluster_resources():
    """Sample cluster resources for testing"""
    return {
        "deployments": [
            Mock(metadata=Mock(namespace="default", name="app1")),
            Mock(metadata=Mock(namespace="kube-system", name="app2"))
        ],
        "pods": [
            Mock(metadata=Mock(namespace="default", name="pod1")),
            Mock(metadata=Mock(namespace="default", name="pod2"))
        ],
        "services": [
            Mock(metadata=Mock(namespace="default", name="service1"))
        ]
    }


@pytest.fixture
def sample_watch_event():
    """Sample watch event for testing"""
    event = Mock(spec=WatchEvent)
    event.resource_type = "deployments"
    event.obj_namespace = "default"
    event.obj_name = "test-deployment"
    event.is_deleted = False
    event.object = Mock(metadata=Mock(namespace="default", name="test-deployment"))
    return event


@pytest.fixture
def sample_cluster_status():
    """Sample cluster status for testing"""
    return ClusterStatus(
        cluster_name="test-cluster",
        state=ClusterState.ACTIVE,
        last_heartbeat=datetime.now(timezone.utc),
        error_message=None,
        heartbeat_failures=0
    )


def test_singleton_pattern(mock_redis):
    """Test that MonitoringRedisClient follows singleton pattern"""
    MonitoringRedisClient._instance = None
    
    client1 = MonitoringRedisClient(settings)
    client2 = MonitoringRedisClient(settings)
    
    assert client1 is client2
    assert MonitoringRedisClient._instance is client1


def test_initialize_redis_connection_success(mock_redis):
    """Test successful Redis connection initialization"""
    MonitoringRedisClient._instance = None
    mock_redis.ping.return_value = True
    
    client = MonitoringRedisClient(settings)
    
    assert client.redis is mock_redis
    mock_redis.ping.assert_called_once()


def test_initialize_redis_connection_failure():
    """Test Redis connection failure"""
    MonitoringRedisClient._instance = None
    
    with patch('chutes_common.redis.Redis') as mock_redis_class:
        mock_redis_class.from_url.side_effect = Exception("Connection failed")
        
        with pytest.raises(Exception, match="Connection failed"):
            MonitoringRedisClient(settings)


def test_close_connection(redis_client, mock_redis):
    """Test closing Redis connection"""
    redis_client.close()
    mock_redis.close.assert_called_once()


@pytest.mark.asyncio
async def test_track_cluster(redis_client, mock_redis, sample_cluster_resources):
    """Test tracking a new cluster"""
    cluster_name = "test-cluster"
    
    with patch.object(redis_client, 'update_cluster_status') as mock_update_status, \
         patch.object(redis_client, 'store_initial_resources') as mock_store_resources:
        
        await redis_client.track_cluster(cluster_name, sample_cluster_resources)
        
        mock_update_status.assert_called_once()
        mock_store_resources.assert_called_once_with(cluster_name, sample_cluster_resources)


@pytest.mark.asyncio
async def test_clear_cluster(redis_client, mock_redis):
    """Test clearing cluster data"""
    cluster_name = "test-cluster"
    
    with patch.object(redis_client, 'clear_cluster_resources') as mock_clear_resources:
        await redis_client.clear_cluster(cluster_name)
        
        mock_clear_resources.assert_called_once_with(cluster_name)
        mock_redis.delete.assert_called_once_with(f"clusters:{cluster_name}:health")


@pytest.mark.asyncio
async def test_clear_cluster_exception(redis_client, mock_redis):
    """Test clear_cluster handles exceptions properly"""
    cluster_name = "test-cluster"
    
    with patch.object(redis_client, 'clear_cluster_resources') as mock_clear_resources:
        mock_clear_resources.side_effect = Exception("Clear failed")
        
        with pytest.raises(Exception, match="Clear failed"):
            await redis_client.clear_cluster(cluster_name)


@pytest.mark.asyncio
async def test_store_initial_resources(redis_client, mock_redis, sample_cluster_resources):
    """Test storing initial resources for a cluster"""
    cluster_name = "test-cluster"
    
    with patch.object(redis_client, 'clear_cluster_resources') as mock_clear, \
         patch('chutes_common.redis.serializer') as mock_serializer:
        
        mock_serializer.serialize.return_value = {"test": "data"}
        
        await redis_client.store_initial_resources(cluster_name, sample_cluster_resources)
        
        mock_clear.assert_called_once_with(cluster_name)
        assert mock_redis.hset.call_count == 3  # deployments, pods, services


@pytest.mark.asyncio
async def test_update_resource_add_or_modify(redis_client, mock_redis, sample_watch_event):
    """Test updating a resource (add or modify)"""
    cluster_name = "test-cluster"
    
    with patch('chutes_common.redis.serializer') as mock_serializer:
        mock_serializer.serialize.return_value = {"test": "data"}
        
        await redis_client.update_resource(cluster_name, sample_watch_event)
        
        expected_key = f"clusters:{cluster_name}:resources:deployments"
        expected_field = "default:test-deployment"
        mock_redis.hset.assert_called_once_with(expected_key, expected_field, json.dumps({"test": "data"}))


@pytest.mark.asyncio
async def test_update_resource_delete(redis_client, mock_redis, sample_watch_event):
    """Test updating a resource (delete)"""
    cluster_name = "test-cluster"
    sample_watch_event.is_deleted = True
    
    await redis_client.update_resource(cluster_name, sample_watch_event)
    
    expected_key = f"clusters:{cluster_name}:resources:deployments"
    expected_field = "default:test-deployment"
    mock_redis.hdel.assert_called_once_with(expected_key, expected_field)


def test_get_resources_single_cluster(redis_client, mock_redis):
    """Test getting resources for a specific cluster"""
    cluster_name = "test-cluster"
    resource_type = ResourceType.DEPLOYMENT
    
    mock_redis.keys.return_value = [f"clusters:{cluster_name}:resources:{resource_type.value}"]
    mock_redis.hgetall.return_value = {
        "default:app1": json.dumps({"name": "app1"}),
        "default:app2": json.dumps({"name": "app2"})
    }
    
    with patch('chutes_common.monitoring.models.ClusterResources.from_dict') as mock_from_dict:
        mock_from_dict.return_value = {"deployments": {"default:app1": {"name": "app1"}}}
        
        result = redis_client.get_resources(cluster_name, resource_type)
        
        mock_redis.keys.assert_called_once_with(f"clusters:{cluster_name}:resources:{resource_type.value}")
        mock_redis.hgetall.assert_called_once()
        mock_from_dict.assert_called_once()


def test_get_resources_all_clusters(redis_client, mock_redis):
    """Test getting resources for all clusters"""
    mock_redis.keys.return_value = [
        "clusters:cluster1:resources:deployments",
        "clusters:cluster2:resources:pods"
    ]
    mock_redis.hgetall.return_value = {}
    
    with patch('chutes_common.monitoring.models.ClusterResources.from_dict') as mock_from_dict:
        mock_from_dict.return_value = {}
        
        result = redis_client.get_resources("*", ResourceType.ALL)
        
        mock_redis.keys.assert_called_once_with("clusters:*:resources:*")


def test_get_resource_cluster_found(redis_client, mock_redis):
    """Test finding cluster for a specific resource"""
    resource_name = "test-deployment"
    resource_type = ResourceType.DEPLOYMENT
    namespace = "default"
    
    mock_redis.keys.return_value = ["clusters:test-cluster:resources:deployment"]
    mock_redis.hkeys.return_value = ["default:test-deployment", "kube-system:other-deployment"]
    
    result = redis_client.get_resource_cluster(resource_name, resource_type, namespace)
    
    assert result == "test-cluster"
    mock_redis.keys.assert_called_once_with("clusters:*:resources:deployment")


def test_get_resource_cluster_not_found(redis_client, mock_redis):
    """Test resource not found in any cluster"""
    resource_name = "missing-deployment"
    resource_type = ResourceType.DEPLOYMENT
    namespace = "default"
    
    mock_redis.keys.return_value = ["clusters:test-cluster:resources:deployment"]
    mock_redis.hkeys.return_value = ["default:other-deployment"]
    
    result = redis_client.get_resource_cluster(resource_name, resource_type, namespace)
    
    assert result is None


def test_get_resource_cluster_multiple_clusters_error(redis_client, mock_redis):
    """Test error when resource found in multiple clusters"""
    resource_name = "test-deployment"
    resource_type = ResourceType.DEPLOYMENT
    namespace = "default"
    
    mock_redis.keys.return_value = [
        "clusters:cluster1:resources:deployment",
        "clusters:cluster2:resources:deployment"
    ]
    mock_redis.hkeys.side_effect = [
        ["default:test-deployment"],
        ["default:test-deployment"]
    ]
    
    with pytest.raises(ValueError, match="Found multiple clusters"):
        redis_client.get_resource_cluster(resource_name, resource_type, namespace)


@pytest.mark.asyncio
async def test_clear_cluster_resources(redis_client, mock_redis):
    """Test clearing all resources for a cluster"""
    cluster_name = "test-cluster"
    mock_redis.keys.return_value = [
        f"clusters:{cluster_name}:resources:deployments",
        f"clusters:{cluster_name}:resources:pods"
    ]
    
    await redis_client.clear_cluster_resources(cluster_name)
    
    mock_redis.keys.assert_called_once_with(f"clusters:{cluster_name}:resources:*")
    mock_redis.delete.assert_called_once()


@pytest.mark.asyncio
async def test_clear_cluster_resources_no_keys(redis_client, mock_redis):
    """Test clearing resources when no keys exist"""
    cluster_name = "test-cluster"
    mock_redis.keys.return_value = []
    
    await redis_client.clear_cluster_resources(cluster_name)
    
    mock_redis.keys.assert_called_once_with(f"clusters:{cluster_name}:resources:*")
    mock_redis.delete.assert_not_called()


@pytest.mark.asyncio
async def test_update_cluster_status(redis_client, mock_redis, sample_cluster_status):
    """Test updating cluster status"""
    await redis_client.update_cluster_status(sample_cluster_status)
    
    expected_key = f"clusters:{sample_cluster_status.cluster_name}:health"
    mock_redis.hset.assert_called_once()
    call_args = mock_redis.hset.call_args
    assert call_args[0][0] == expected_key
    assert "cluster_name" in call_args[1]["mapping"]
    assert "state" in call_args[1]["mapping"]


@pytest.mark.asyncio
async def test_increment_health_failures(redis_client, mock_redis):
    """Test incrementing health failure count"""
    cluster_name = "test-cluster"
    mock_redis.hincrby.return_value = 3
    
    result = await redis_client.increment_health_failures(cluster_name)
    
    assert result == 3
    expected_key = f"clusters:{cluster_name}:health"
    mock_redis.hincrby.assert_called_once_with(expected_key, "failures", 1)
    mock_redis.expire.assert_called_once_with(expected_key, 300)


@pytest.mark.asyncio
async def test_get_cluster_status_exists(redis_client, mock_redis):
    """Test getting cluster status when it exists"""
    cluster_name = "test-cluster"
    mock_redis.hgetall.return_value = {
        "cluster_name": cluster_name,
        "state": "active",
        "last_heartbeat": "2023-01-01T00:00:00+00:00",
        "error_message": "",
        "heartbeat_failures": "0"
    }
    
    result = await redis_client.get_cluster_status(cluster_name)
    
    assert result is not None
    assert result.cluster_name == cluster_name
    assert result.state == ClusterState.ACTIVE
    assert result.heartbeat_failures == 0


@pytest.mark.asyncio
async def test_get_cluster_status_not_exists(redis_client, mock_redis):
    """Test getting cluster status when it doesn't exist"""
    cluster_name = "test-cluster"
    mock_redis.hgetall.return_value = {}
    
    result = await redis_client.get_cluster_status(cluster_name)
    
    assert result is None


@pytest.mark.asyncio
async def test_get_all_cluster_statuses(redis_client, mock_redis):
    """Test getting all cluster statuses"""
    mock_redis.keys.return_value = [
        "clusters:cluster1:health",
        "clusters:cluster2:health"
    ]
    
    # Mock pipeline
    mock_pipeline = Mock()
    mock_redis.pipeline.return_value = mock_pipeline
    mock_pipeline.execute.return_value = [
        {"cluster_name": "cluster1", "state": "active", "last_heartbeat": "", "error_message": "", "heartbeat_failures": "0"},
        {"cluster_name": "cluster2", "state": "starting", "last_heartbeat": "", "error_message": "", "heartbeat_failures": "1"}
    ]
    
    result = await redis_client.get_all_cluster_statuses()
    
    assert len(result) == 2
    assert result[0].cluster_name == "cluster1"
    assert result[1].cluster_name == "cluster2"
    mock_redis.pipeline.assert_called_once()


@pytest.mark.asyncio
async def test_get_all_cluster_names(redis_client, mock_redis):
    """Test getting all cluster names"""
    mock_redis.keys.return_value = [
        "clusters:cluster1:health",
        "clusters:cluster2:health",
        "clusters:cluster3:health"
    ]
    
    result = redis_client.get_all_cluster_names()
    
    assert result == ["cluster1", "cluster2", "cluster3"]
    mock_redis.keys.assert_called_once_with("clusters:*:health")


@pytest.mark.asyncio
async def test_get_resource_counts(redis_client, mock_redis):
    """Test getting resource counts for a cluster"""
    cluster_name = "test-cluster"
    mock_redis.hlen.side_effect = [5, 10, 3]  # deployments, pods, services
    
    result = redis_client.get_resource_counts(cluster_name)
    
    assert result == {
        "deployments": 5,
        "pods": 10,
        "services": 3
    }
    assert mock_redis.hlen.call_count == 3


@pytest.mark.asyncio
async def test_get_all_cluster_statuses_empty(redis_client, mock_redis):
    """Test getting all cluster statuses when none exist"""
    mock_redis.keys.return_value = []
    
    result = await redis_client.get_all_cluster_statuses()
    
    assert result == []
    mock_redis.keys.assert_called_once_with("clusters:*:health")


def test_redis_property(redis_client, mock_redis):
    """Test redis property returns the correct instance"""
    assert redis_client.redis is mock_redis


@pytest.mark.asyncio 
async def test_store_initial_resources_empty_items(redis_client, mock_redis):
    """Test storing initial resources with empty items"""
    cluster_name = "test-cluster"
    resources = {"deployments": [], "pods": None, "services": [Mock(metadata=Mock(namespace="default", name="svc1"))]}
    
    with patch.object(redis_client, 'clear_cluster_resources') as mock_clear, \
         patch('chutes_common.redis.serializer') as mock_serializer:
        
        mock_serializer.serialize.return_value = {"test": "data"}
        
        await redis_client.store_initial_resources(cluster_name, resources)
        
        mock_clear.assert_called_once_with(cluster_name)
        # Should only call hset once for services (deployments and pods are empty/None)
        mock_redis.hset.assert_called_once()


# Filtering tests
def test_filter_resources_no_filters(redis_client):
    """Test _filter_resources with no filters applied"""
    resources = {
        "default:app1": json.dumps({"name": "app1"}),
        "kube-system:app2": json.dumps({"name": "app2"}),
        "default:app3": json.dumps({"name": "app3"})
    }
    
    result = redis_client._filter_resources(resources)
    
    assert result == resources


def test_filter_resources_by_namespace(redis_client):
    """Test _filter_resources filtering by namespace"""
    resources = {
        "default:app1": json.dumps({"name": "app1"}),
        "kube-system:app2": json.dumps({"name": "app2"}),
        "default:app3": json.dumps({"name": "app3"})
    }
    
    result = redis_client._filter_resources(resources, namespace="default")
    
    expected = {
        "default:app1": json.dumps({"name": "app1"}),
        "default:app3": json.dumps({"name": "app3"})
    }
    assert result == expected


def test_filter_resources_by_resource_name(redis_client):
    """Test _filter_resources filtering by resource name"""
    resources = {
        "default:app1": json.dumps({"name": "app1"}),
        "kube-system:app2": json.dumps({"name": "app2"}),
        "default:app3": json.dumps({"name": "app3"})
    }
    
    result = redis_client._filter_resources(resources, resource_name="app1")
    
    expected = {
        "default:app1": json.dumps({"name": "app1"})
    }
    assert result == expected


def test_filter_resources_by_both_namespace_and_name(redis_client):
    """Test _filter_resources filtering by both namespace and resource name"""
    resources = {
        "default:app1": json.dumps({"name": "app1"}),
        "kube-system:app1": json.dumps({"name": "app1"}),
        "default:app2": json.dumps({"name": "app2"})
    }
    
    result = redis_client._filter_resources(resources, resource_name="app1", namespace="default")
    
    expected = {
        "default:app1": json.dumps({"name": "app1"})
    }
    assert result == expected


def test_filter_resources_no_matches(redis_client):
    """Test _filter_resources with no matches"""
    resources = {
        "default:app1": json.dumps({"name": "app1"}),
        "kube-system:app2": json.dumps({"name": "app2"})
    }
    
    result = redis_client._filter_resources(resources, resource_name="nonexistent")
    
    assert result == {}


def test_filter_resources_empty_input(redis_client):
    """Test _filter_resources with empty input"""
    resources = {}
    
    result = redis_client._filter_resources(resources, resource_name="app1", namespace="default")
    
    assert result == {}


def test_get_resources_with_namespace_filter(redis_client, mock_redis):
    """Test get_resources with namespace filter"""
    cluster_name = "test-cluster"
    resource_type = ResourceType.DEPLOYMENT
    namespace = "default"
    
    mock_redis.keys.return_value = [f"clusters:{cluster_name}:resources:{resource_type.value}"]
    mock_redis.hgetall.return_value = {
        "default:app1": json.dumps({"name": "app1"}),
        "kube-system:app2": json.dumps({"name": "app2"}),
        "default:app3": json.dumps({"name": "app3"})
    }
    
    with patch('chutes_common.monitoring.models.ClusterResources.from_dict') as mock_from_dict:
        mock_from_dict.return_value = {"deployments": {"default:app1": {"name": "app1"}}}
        
        result = redis_client.get_resources(cluster_name, resource_type, namespace=namespace)
        
        mock_redis.keys.assert_called_once_with(f"clusters:{cluster_name}:resources:{resource_type.value}")
        mock_redis.hgetall.assert_called_once()
        
        # Verify that from_dict was called with filtered resources
        call_args = mock_from_dict.call_args[0][0]
        assert "default:app1" in call_args["deployment"]
        assert "default:app3" in call_args["deployment"]
        assert "kube-system:app2" not in call_args["deployment"]


def test_get_resources_with_resource_name_filter(redis_client, mock_redis):
    """Test get_resources with resource name filter"""
    cluster_name = "test-cluster"
    resource_type = ResourceType.DEPLOYMENT
    resource_name = "app1"
    
    mock_redis.keys.return_value = [f"clusters:{cluster_name}:resources:{resource_type.value}"]
    mock_redis.hgetall.return_value = {
        "default:app1": json.dumps({"name": "app1"}),
        "kube-system:app1": json.dumps({"name": "app1"}),
        "default:app2": json.dumps({"name": "app2"})
    }
    
    with patch('chutes_common.monitoring.models.ClusterResources.from_dict') as mock_from_dict:
        mock_from_dict.return_value = {"deployments": {"default:app1": {"name": "app1"}}}
        
        result = redis_client.get_resources(cluster_name, resource_type, resource_name=resource_name)
        
        mock_redis.keys.assert_called_once_with(f"clusters:{cluster_name}:resources:{resource_type.value}")
        mock_redis.hgetall.assert_called_once()
        
        # Verify that from_dict was called with filtered resources
        call_args = mock_from_dict.call_args[0][0]
        assert "default:app1" in call_args["deployment"]
        assert "kube-system:app1" in call_args["deployment"]
        assert "default:app2" not in call_args["deployment"]


def test_get_resources_with_both_filters(redis_client, mock_redis):
    """Test get_resources with both namespace and resource name filters"""
    cluster_name = "test-cluster"
    resource_type = ResourceType.DEPLOYMENT
    resource_name = "app1"
    namespace = "default"
    
    mock_redis.keys.return_value = [f"clusters:{cluster_name}:resources:{resource_type.value}"]
    mock_redis.hgetall.return_value = {
        "default:app1": json.dumps({"name": "app1"}),
        "kube-system:app1": json.dumps({"name": "app1"}),
        "default:app2": json.dumps({"name": "app2"})
    }
    
    with patch('chutes_common.monitoring.models.ClusterResources.from_dict') as mock_from_dict:
        mock_from_dict.return_value = {"deployments": {"default:app1": {"name": "app1"}}}
        
        result = redis_client.get_resources(cluster_name, resource_type, resource_name=resource_name, namespace=namespace)
        
        mock_redis.keys.assert_called_once_with(f"clusters:{cluster_name}:resources:{resource_type.value}")
        mock_redis.hgetall.assert_called_once()
        
        # Verify that from_dict was called with filtered resources
        call_args = mock_from_dict.call_args[0][0]
        assert "default:app1" in call_args["deployment"]
        assert "kube-system:app1" not in call_args["deployment"]
        assert "default:app2" not in call_args["deployment"]


def test_get_resources_with_filters_no_matches(redis_client, mock_redis):
    """Test get_resources with filters that match no resources"""
    cluster_name = "test-cluster"
    resource_type = ResourceType.DEPLOYMENT
    resource_name = "nonexistent"
    
    mock_redis.keys.return_value = [f"clusters:{cluster_name}:resources:{resource_type.value}"]
    mock_redis.hgetall.return_value = {
        "default:app1": json.dumps({"name": "app1"}),
        "kube-system:app2": json.dumps({"name": "app2"})
    }
    
    with patch('chutes_common.monitoring.models.ClusterResources.from_dict') as mock_from_dict:
        mock_from_dict.return_value = {"deployments": {}}
        
        result = redis_client.get_resources(cluster_name, resource_type, resource_name=resource_name)
        
        mock_redis.keys.assert_called_once_with(f"clusters:{cluster_name}:resources:{resource_type.value}")
        mock_redis.hgetall.assert_called_once()
        
        # Verify that from_dict was called with empty filtered resources
        call_args = mock_from_dict.call_args[0][0]
        assert call_args["deployment"] == {}


def test_get_resources_multiple_resource_types_with_filters(redis_client, mock_redis):
    """Test get_resources with multiple resource types and filters"""
    cluster_name = "test-cluster"
    resource_type = ResourceType.ALL
    namespace = "default"
    
    mock_redis.keys.return_value = [
        f"clusters:{cluster_name}:resources:deployment",
        f"clusters:{cluster_name}:resources:pod"
    ]
    
    # Mock hgetall to return different data for different resource types
    def mock_hgetall(key):
        if key.endswith(":deployment"):
            return {
                "default:deploy1": json.dumps({"name": "deploy1"}),
                "kube-system:deploy2": json.dumps({"name": "deploy2"})
            }
        elif key.endswith(":pod"):
            return {
                "default:pod1": json.dumps({"name": "pod1"}),
                "kube-system:pod2": json.dumps({"name": "pod2"})
            }
        return {}
    
    mock_redis.hgetall.side_effect = mock_hgetall
    
    with patch('chutes_common.monitoring.models.ClusterResources.from_dict') as mock_from_dict:
        mock_from_dict.return_value = {"deployment": {}, "pod": {}}
        
        result = redis_client.get_resources(cluster_name, resource_type, namespace=namespace)
        
        mock_redis.keys.assert_called_once_with(f"clusters:{cluster_name}:resources:*")
        assert mock_redis.hgetall.call_count == 2
        
        # Verify that from_dict was called with filtered resources from both types
        call_args = mock_from_dict.call_args[0][0]
        assert "deployment" in call_args
        assert "pod" in call_args
        # Check that only default namespace resources are included
        assert "default:deploy1" in call_args["deployment"]
        assert "kube-system:deploy2" not in call_args["deployment"]
        assert "default:pod1" in call_args["pod"]
        assert "kube-system:pod2" not in call_args["pod"]


def test_get_resources_with_filters_single_resource_type(redis_client, mock_redis):
    """Test get_resources with filters for a single resource type"""
    cluster_name = "test-cluster"
    resource_type = ResourceType.POD
    resource_name = "pod1"
    
    mock_redis.keys.return_value = [f"clusters:{cluster_name}:resources:{resource_type.value}"]
    mock_redis.hgetall.return_value = {
        "default:pod1": json.dumps({"name": "pod1"}),
        "default:pod2": json.dumps({"name": "pod2"}),
        "kube-system:pod1": json.dumps({"name": "pod1"})
    }
    
    with patch('chutes_common.monitoring.models.ClusterResources.from_dict') as mock_from_dict:
        mock_from_dict.return_value = {"pods": {}}
        
        result = redis_client.get_resources(cluster_name, resource_type, resource_name=resource_name)
        
        mock_redis.keys.assert_called_once_with(f"clusters:{cluster_name}:resources:{resource_type.value}")
        mock_redis.hgetall.assert_called_once()
        
        # Verify that from_dict was called with filtered resources
        call_args = mock_from_dict.call_args[0][0]
        assert "default:pod1" in call_args["pod"]
        assert "kube-system:pod1" in call_args["pod"]
        assert "default:pod2" not in call_args["pod"]


def test_get_resources_with_namespace_filter_empty_namespace(redis_client, mock_redis):
    """Test get_resources with empty namespace filter"""
    cluster_name = "test-cluster"
    resource_type = ResourceType.DEPLOYMENT
    namespace = ""
    
    mock_redis.keys.return_value = [f"clusters:{cluster_name}:resources:{resource_type.value}"]
    mock_redis.hgetall.return_value = {
        "default:app1": json.dumps({"name": "app1"}),
        "kube-system:app2": json.dumps({"name": "app2"})
    }
    
    with patch('chutes_common.monitoring.models.ClusterResources.from_dict') as mock_from_dict:
        mock_from_dict.return_value = {"deployments": {}}
        
        result = redis_client.get_resources(cluster_name, resource_type, namespace=namespace)
        
        # Empty namespace should return all resources (no filtering)
        call_args = mock_from_dict.call_args[0][0]
        assert "default:app1" in call_args["deployment"]
        assert "kube-system:app2" in call_args["deployment"]


def test_get_resources_with_none_filters(redis_client, mock_redis):
    """Test get_resources with None filters"""
    cluster_name = "test-cluster"
    resource_type = ResourceType.DEPLOYMENT
    
    mock_redis.keys.return_value = [f"clusters:{cluster_name}:resources:{resource_type.value}"]
    mock_redis.hgetall.return_value = {
        "default:app1": json.dumps({"name": "app1"}),
        "kube-system:app2": json.dumps({"name": "app2"})
    }
    
    with patch('chutes_common.monitoring.models.ClusterResources.from_dict') as mock_from_dict:
        mock_from_dict.return_value = {"deployments": {}}
        
        result = redis_client.get_resources(cluster_name, resource_type, resource_name=None, namespace=None)
        
        # None filters should return all resources (no filtering)
        call_args = mock_from_dict.call_args[0][0]
        assert "default:app1" in call_args["deployment"]
        assert "kube-system:app2" in call_args["deployment"]


def test_filter_resources_case_sensitive(redis_client):
    """Test _filter_resources is case sensitive"""
    resources = {
        "default:App1": json.dumps({"name": "App1"}),
        "default:app1": json.dumps({"name": "app1"}),
        "Default:app1": json.dumps({"name": "app1"})
    }
    
    # Test case sensitive resource name filtering
    result = redis_client._filter_resources(resources, resource_name="app1")
    expected = {
        "default:app1": json.dumps({"name": "app1"}),
        "Default:app1": json.dumps({"name": "app1"})
    }
    assert result == expected
    
    # Test case sensitive namespace filtering
    result = redis_client._filter_resources(resources, namespace="default")
    expected = {
        "default:App1": json.dumps({"name": "App1"}),
        "default:app1": json.dumps({"name": "app1"})
    }
    assert result == expected


def test_filter_resources_special_characters(redis_client):
    """Test _filter_resources with special characters in names"""
    resources = {
        "default:app-with-dashes": json.dumps({"name": "app-with-dashes"}),
        "default:app_with_underscores": json.dumps({"name": "app_with_underscores"}),
        "default:app.with.dots": json.dumps({"name": "app.with.dots"}),
        "namespace-with-dashes:app1": json.dumps({"name": "app1"})
    }
    
    # Test filtering by resource name with special characters
    result = redis_client._filter_resources(resources, resource_name="app-with-dashes")
    expected = {
        "default:app-with-dashes": json.dumps({"name": "app-with-dashes"})
    }
    assert result == expected
    
    # Test filtering by namespace with special characters
    result = redis_client._filter_resources(resources, namespace="namespace-with-dashes")
    expected = {
        "namespace-with-dashes:app1": json.dumps({"name": "app1"})
    }
    assert result == expected


def test_filter_resources_performance_with_large_dataset(redis_client):
    """Test _filter_resources performance with a large dataset"""
    # Create a large dataset
    resources = {}
    for i in range(1000):
        namespace = f"namespace-{i % 10}"
        resource_name = f"app-{i}"
        resources[f"{namespace}:{resource_name}"] = json.dumps({"name": resource_name})
    
    # Filter by namespace should return 100 resources (1000 / 10 namespaces)
    result = redis_client._filter_resources(resources, namespace="namespace-1")
    assert len(result) == 100
    
    # Filter by specific resource name should return 1 resource
    result = redis_client._filter_resources(resources, resource_name="app-500")
    assert len(result) == 1
    assert "namespace-0:app-500" in result


def test_get_resources_with_wildcard_cluster_and_filters(redis_client, mock_redis):
    """Test get_resources with wildcard cluster and filters"""
    resource_type = ResourceType.DEPLOYMENT
    namespace = "default"
    
    mock_redis.keys.return_value = [
        "clusters:cluster1:resources:deployment",
        "clusters:cluster2:resources:deployment"
    ]
    
    def mock_hgetall(key):
        if "cluster1" in key:
            return {
                "default:app1": json.dumps({"name": "app1"}),
                "kube-system:app2": json.dumps({"name": "app2"})
            }
        elif "cluster2" in key:
            return {
                "default:app3": json.dumps({"name": "app3"}),
                "kube-system:app4": json.dumps({"name": "app4"})
            }
        return {}
    
    mock_redis.hgetall.side_effect = mock_hgetall
    
    with patch('chutes_common.monitoring.models.ClusterResources.from_dict') as mock_from_dict:
        mock_from_dict.return_value = {"deployment": {}}
        
        result = redis_client.get_resources("*", resource_type, namespace=namespace)
        
        mock_redis.keys.assert_called_once_with("clusters:*:resources:deployment")
        assert mock_redis.hgetall.call_count == 2
        
        # Verify that from_dict was called with filtered resources from both clusters
        call_args = mock_from_dict.call_args[0][0]
        assert "deployment" in call_args
        # Should include default namespace resources from both clusters
        assert "default:app1" in call_args["deployment"]
        assert "default:app3" in call_args["deployment"]
        # Should exclude kube-system namespace resources
        assert "kube-system:app2" not in call_args["deployment"]
        assert "kube-system:app4" not in call_args["deployment"]