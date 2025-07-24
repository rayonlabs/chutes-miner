"""
Unit tests for kubernetes helper module.
"""

import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock, Mock, patch
from kubernetes.client import V1PodList
from kubernetes.client.rest import ApiException
from datetime import datetime

# Import the module under test
from chutes_miner.api.deployment.schemas import Deployment
import chutes_miner.api.k8s as k8s
from chutes_miner.api.exceptions import DeploymentFailure
from chutes_miner.api.k8s.operator import K8sOperator, SingleClusterK8sOperator
from chutes_common.k8s import serializer


@pytest.fixture(autouse=True, scope="function")
def mock_k8s_operator_single_cluster():
    # Save the original __new__ method
    original_new = K8sOperator.__new__

    # Create a mock implementation that always returns SingleClusterK8sOperator
    def mock_new(cls, *args, **kwargs):
        return super(K8sOperator, cls).__new__(SingleClusterK8sOperator)

    # Apply the mock
    K8sOperator.__new__ = mock_new

    # Clear any singleton instance that might exist
    K8sOperator._instance = None

    yield

    # Restore the original method after test
    K8sOperator.__new__ = original_new
    K8sOperator._instance = None

@pytest.fixture(autouse=True)
def multicluster_setup(
    mock_k8s_batch_client, mock_k8s_app_client, mock_k8s_core_client
):    
    pass


# Tests for get_kubernetes_nodes
@pytest.mark.asyncio
async def test_get_kubernetes_nodes_success(mock_k8s_core_client):
    """Test successful retrieval of kubernetes nodes."""
    # Setup mock response
    node_list = MagicMock()
    node1 = MagicMock()
    node1.metadata.name = "node1"
    node1.metadata.labels = {"chutes/validator": "TEST123", "chutes/external-ip": "192.168.1.100"}
    node1.metadata.uid = "node1-uid"
    node1.status.phase = "Ready"
    node1.status.capacity = {"cpu": "8", "memory": "32Gi", "nvidia.com/gpu": "2"}
    node1.metadata.labels["nvidia.com/gpu.memory"] = "16384"  # 16GB

    node_list.items = [node1]
    mock_k8s_core_client.list_node.return_value = node_list

    # Call the function
    # k8s_core_client.cache_clear()
    result = await k8s.get_kubernetes_nodes()

    # Assertions
    mock_k8s_core_client.list_node.assert_called_once_with(
        field_selector=None, label_selector="chutes/worker"
    )

    assert len(result) == 1
    assert result[0]["name"] == "node1"
    assert result[0]["validator"] == "TEST123"
    assert result[0]["server_id"] == "node1-uid"
    assert result[0]["status"] == "Ready"
    assert result[0]["ip_address"] == "192.168.1.100"
    assert result[0]["cpu_per_gpu"] == 3  # (8-2)/2 but capped at min(4, floor(cpu/gpu))
    assert result[0]["memory_gb_per_gpu"] == 10  # min(16, floor(26*0.8/2))


@pytest.mark.asyncio
async def test_get_kubernetes_nodes_exception(mock_k8s_core_client):
    """Test exception handling when retrieving kubernetes nodes."""
    # Setup mock to raise an exception
    mock_k8s_core_client.list_node.side_effect = Exception("API Error")

    # Call the function and expect exception
    with pytest.raises(Exception, match="API Error"):
        await k8s.get_kubernetes_nodes()


# # Tests for is_deployment_ready
def test_is_deployment_ready_true():
    """Test deployment is ready when all conditions are met."""
    deployment = MagicMock()
    deployment.status.available_replicas = 1
    deployment.status.ready_replicas = 1
    deployment.status.updated_replicas = 1
    deployment.spec.replicas = 1

    assert k8s.K8sOperator()._is_deployment_ready(deployment) is True


def test_is_deployment_ready_false_available_replicas_none():
    """Test deployment is not ready when available_replicas is None."""
    deployment = MagicMock()
    deployment.status.available_replicas = None
    deployment.status.ready_replicas = 1
    deployment.status.updated_replicas = 1
    deployment.spec.replicas = 1

    assert k8s.K8sOperator()._is_deployment_ready(deployment) is False


def test_is_deployment_ready_false_not_matching():
    """Test deployment is not ready when replicas don't match."""
    deployment = MagicMock()
    deployment.status.available_replicas = 1
    deployment.status.ready_replicas = 0  # Not matching
    deployment.status.updated_replicas = 1
    deployment.spec.replicas = 1

    assert k8s.K8sOperator()._is_deployment_ready(deployment) is False


# Tests for extract_deployment_info
def test_extract_deployment_info(mock_k8s_core_client):
    """Test extracting deployment info from k8s deployment object."""
    # Setup mock deployment
    deployment = MagicMock()
    deployment.metadata.uid = "test-uid"
    deployment.metadata.name = "test-deployment"
    deployment.metadata.namespace = "test-namespace"
    deployment.metadata.labels = {
        "chutes/deployment-id": "test-deployment-id",
        "chutes/chute-id": "test-chute-id",
        "chutes/version": "1.0.0",
    }
    deployment.spec.template.spec.node_selector = {"key": "value"}
    deployment.spec.selector.match_labels = {"app": "test"}

    # Setup is_deployment_ready mock
    deployment.status.available_replicas = 1
    deployment.status.ready_replicas = 1
    deployment.status.updated_replicas = 1
    deployment.spec.replicas = 1

    # Setup pod list mock
    pod = MagicMock()
    pod.metadata.name = "test-pod"
    pod.status.phase = "Running"
    container_status = MagicMock()
    container_status.restart_count = 0

    # Add state running
    state_running = MagicMock()
    state_running.to_dict.return_value = {
        "startedAt": datetime.fromisoformat("2023-01-01T00:00:00Z")
    }
    container_status.state = MagicMock()
    container_status.state.running = state_running
    container_status.state.terminated = None
    container_status.state.waiting = None

    # Add last state terminated
    last_state_terminated = MagicMock()
    last_state_terminated.to_dict.return_value = {"exitCode": 0, "reason": "Completed"}
    container_status.last_state = MagicMock()
    container_status.last_state.running = None
    container_status.last_state.terminated = last_state_terminated
    container_status.last_state.waiting = None

    pod.status.container_statuses = [container_status]
    pod.spec.node_name = "node1"

    mock_k8s_core_client.list_namespaced_pod.return_value = MagicMock(items=[pod])

    result = k8s.K8sOperator()._extract_deployment_info(deployment)

    # Assertions
    assert result["uuid"] == "test-uid"
    assert result["deployment_id"] == "test-deployment-id"
    assert result["name"] == "test-deployment"
    assert result["namespace"] == "test-namespace"
    assert result["chute_id"] == "test-chute-id"
    assert result["version"] == "1.0.0"
    assert result["ready"] is True
    assert result["node"] == "node1"
    assert len(result["pods"]) == 1
    assert result["pods"][0]["name"] == "test-pod"
    assert result["pods"][0]["phase"] == "Running"
    assert result["pods"][0]["restart_count"] == 0
    assert result["pods"][0]["state"]["running"] == {
        "startedAt": datetime.fromisoformat("2023-01-01T00:00:00Z")
    }
    assert result["pods"][0]["last_state"]["terminated"] == {"exitCode": 0, "reason": "Completed"}


# Tests for get_deployment
@pytest.mark.asyncio
async def test_get_deployment(mock_k8s_batch_client):
    """Test getting a single deployment by ID."""
    # Setup mock
    deployment = MagicMock()
    deployment.metadata.uid = "test-uid"
    deployment.metadata.name = "chute-test-deployment-id"
    deployment.metadata.namespace = "test-namespace"
    deployment.metadata.labels = {
        "chutes/deployment-id": "test-deployment-id",
        "chutes/chute-id": "test-chute-id",
        "chutes/version": "1.0.0",
    }

    mock_k8s_batch_client.read_namespaced_job.return_value = deployment

    # Setup extract_deployment_info mock
    with patch(
        "chutes_miner.api.k8s.operator.K8sOperator._extract_job_info"
    ) as mock_extract:
        mock_extract.return_value = {"name": "test-deployment"}

        # Call the function
        result = await k8s.get_deployment("test-deployment-id")

        # Assertions
        mock_k8s_batch_client.read_namespaced_job.assert_called_once()
        mock_extract.assert_called_once_with(deployment)
        assert result == {"name": "test-deployment"}


# Tests for get_deployed_chutes
@pytest.mark.asyncio
async def test_get_deployed_chutes(mock_k8s_batch_client):
    """Test getting all deployed chutes."""
    # Setup mock
    deployment1 = MagicMock()
    deployment1.metadata.name = "chute-1"
    deployment1.metadata.namespace = "test-namespace"
    deployment2 = MagicMock()
    deployment2.metadata.name = "chute-2"
    deployment2.metadata.namespace = "test-namespace"

    job_list = MagicMock()
    job_list.items = [deployment1, deployment2]
    mock_k8s_batch_client.list_namespaced_job.return_value = job_list

    # Setup extract_deployment_info mock
    with patch(
        "chutes_miner.api.k8s.operator.K8sOperator._extract_job_info"
    ) as mock_extract:
        mock_extract.side_effect = [
            {"name": "chute-1", "chute_id": "id1"},
            {"name": "chute-2", "chute_id": "id2"},
        ]

        # Call the function
        result = await k8s.get_deployed_chutes()

        # Assertions
        mock_k8s_batch_client.list_namespaced_job.assert_called_once()
        assert mock_extract.call_count == 2
        assert len(result) == 2
        assert result[0]["name"] == "chute-1"
        assert result[1]["name"] == "chute-2"


# Tests for delete_code
@pytest.mark.asyncio
async def test_delete_code_success(mock_k8s_core_client):
    """Test successful deletion of code configmap."""
    # Call the function
    await k8s.delete_code("test-chute-id", "1.0.0")

    # Assertions
    mock_k8s_core_client.delete_namespaced_config_map.assert_called_once()
    # Verify the name is based on the UUID generated from chute_id and version
    assert "chute-code-" in mock_k8s_core_client.delete_namespaced_config_map.call_args[1]["name"]


@pytest.mark.asyncio
async def test_delete_code_not_found(mock_k8s_core_client):
    """Test handling of 404 error when deleting configmap."""
    # Setup mock to raise ApiException with 404
    error = ApiException(status=404)
    mock_k8s_core_client.delete_namespaced_config_map.side_effect = error

    # Call the function - should not raise exception
    await k8s.delete_code("test-chute-id", "1.0.0")

    # Assertions
    mock_k8s_core_client.delete_namespaced_config_map.assert_called_once()


@pytest.mark.asyncio
async def test_delete_code_other_error(mock_k8s_core_client):
    """Test handling of non-404 error when deleting configmap."""
    # Setup mock to raise ApiException with 500
    error = ApiException(status=500)
    mock_k8s_core_client.delete_namespaced_config_map.side_effect = error

    # Call the function and expect exception
    with pytest.raises(ApiException):
        await k8s.delete_code("test-chute-id", "1.0.0")


# Tests for wait_for_deletion
@pytest.mark.asyncio
async def test_wait_for_deletion_no_pods(mock_k8s_core_client):
    """Test wait_for_deletion when no pods match the label."""
    # Setup mock to return empty list
    pod_list = MagicMock()
    pod_list.items = []
    mock_k8s_core_client.list_namespaced_pod.return_value = pod_list

    # Call the function
    await k8s.wait_for_deletion("app=test")

    # Assertions
    mock_k8s_core_client.list_namespaced_pod.assert_called_once()


@pytest.mark.asyncio
async def test_wait_for_deletion_with_pods(mock_k8s_core_client, mock_watch):
    """Test wait_for_deletion when pods exist and then get deleted."""
    # Setup mock to return pods initially, then empty
    pod_list_with_pods = MagicMock()
    pod_list_with_pods.items = [MagicMock()]

    pod_list_empty = MagicMock()
    pod_list_empty.items = []

    mock_k8s_core_client.list_namespaced_pod.side_effect = [
        pod_list_with_pods,  # Initial check - pods exist
        pod_list_empty,  # Check in the watch loop - pods gone
    ]

    mock_event = Mock()
    mock_event.is_deleted = True
    mock_watch.stream.return_value = [mock_event]

    with patch("chutes_miner.api.k8s.operator.WatchEvent") as mock_event_class:
        mock_event_class.from_dict.return_value = mock_event

        # Call the function
        await k8s.wait_for_deletion("app=test")

    # Assertions
    assert mock_k8s_core_client.list_namespaced_pod.call_count == 1


# Tests for undeploy
@pytest.mark.asyncio
async def test_undeploy_success(mock_k8s_core_client, mock_k8s_batch_client):
    """Test successful undeployment of a chute."""
    # Setup mocks
    with patch("chutes_miner.api.k8s.operator.K8sOperator.wait_for_deletion") as mock_wait:
        # Call the function
        await k8s.undeploy("test-deployment-id")

        # Assertions
        mock_k8s_core_client.delete_namespaced_service.assert_called_once()
        mock_k8s_batch_client.delete_namespaced_job.assert_called_once()
        mock_wait.assert_called_once()


@pytest.mark.asyncio
async def test_undeploy_with_service_error(mock_k8s_core_client, mock_k8s_batch_client):
    """Test undeployment when service deletion fails."""
    # Setup service deletion to fail
    mock_k8s_core_client.delete_namespaced_service.side_effect = Exception("Service error")

    # Setup remaining mocks
    with patch("chutes_miner.api.k8s.operator.K8sOperator.wait_for_deletion") as mock_wait:
        # Call the function - should not raise exception
        await k8s.undeploy("test-deployment-id")

        # Assertions
        mock_k8s_core_client.delete_namespaced_service.assert_called_once()
        mock_k8s_batch_client.delete_namespaced_job.assert_called_once()
        mock_wait.assert_called_once()


# Tests for create_code_config_map
@pytest.mark.asyncio
async def test_create_code_config_map_success(mock_k8s_core_client):
    """Test successful creation of code configmap."""
    # Setup mock chute
    chute = MagicMock()
    chute.chute_id = "test-chute-id"
    chute.version = "1.0.0"
    chute.filename = "app.py"
    chute.code = "print('Hello World')"

    # Call the function
    await k8s.create_code_config_map(chute)

    # Assertions
    mock_k8s_core_client.create_namespaced_config_map.assert_called_once()
    # Check configmap data
    called_config_map = mock_k8s_core_client.create_namespaced_config_map.call_args[1]["body"]
    assert called_config_map.data["app.py"] == "print('Hello World')"


@pytest.mark.asyncio
async def test_create_code_config_map_conflict(mock_k8s_core_client):
    """Test handling of 409 conflict when creating configmap."""
    # Setup mock to raise ApiException with 409
    error = ApiException(status=409)
    mock_k8s_core_client.create_namespaced_config_map.side_effect = error

    # Setup mock chute
    chute = MagicMock()
    chute.chute_id = "test-chute-id"
    chute.version = "1.0.0"
    chute.filename = "app.py"
    chute.code = "print('Hello World')"

    # Call the function - should not raise exception
    await k8s.create_code_config_map(chute)

    # Assertions
    mock_k8s_core_client.create_namespaced_config_map.assert_called_once()


@pytest.mark.asyncio
async def test_create_code_config_map_other_error(mock_k8s_core_client):
    """Test handling of non-409 error when creating configmap."""
    # Setup mock to raise ApiException with 500
    error = ApiException(status=500)
    mock_k8s_core_client.create_namespaced_config_map.side_effect = error

    # Setup mock chute
    chute = MagicMock()
    chute.chute_id = "test-chute-id"
    chute.version = "1.0.0"
    chute.filename = "app.py"
    chute.code = "print('Hello World')"

    # Call the function and expect exception
    with pytest.raises(ApiException):
        await k8s.create_code_config_map(chute)


# Tests for deploy_chute
@pytest.mark.asyncio
async def test_deploy_chute_success(
    mock_k8s_core_client, mock_k8s_batch_client, mock_db_session, sample_server, sample_chute,
    create_api_test_nodes, create_api_test_pods
):
    """Test successful deployment of a chute."""
    # Setup mocks for kubernetes deployment and service creation
    mock_deployment = MagicMock()
    mock_service = MagicMock()
    mock_service.spec.ports = [MagicMock(node_port=30000), MagicMock(node_port=8000), MagicMock(node_port=8001)]

    mock_k8s_batch_client.create_namespaced_job.return_value = mock_deployment
    mock_k8s_core_client.create_namespaced_service.return_value = mock_service

    # Setup session mock for deployment retrieval
    mock_deployment_db = MagicMock(spec=Deployment)
    mock_deployment_db.deployment_id = uuid.uuid4()
    mock_result = MagicMock()
    mock_result.unique.return_value = mock_result
    mock_result.scalar_one_or_none.side_effect = [sample_chute, sample_server, mock_deployment_db]
    mock_db_session.execute = AsyncMock(return_value=mock_result)
    # mock_session.execute.return_value.unique.return_value.scalar_one_or_none.return_value = mock_deployment_db

    nodes = create_api_test_nodes(1)
    mock_k8s_core_client.read_node.return_value = serializer.deserialize(nodes[0], "V1Node")

    pods = create_api_test_pods(1)
    mock_k8s_core_client.list_namespaced_pod.return_value = V1PodList(items=serializer.deserialize(pods, "list[V1Pod]"))

    # Call the function
    with patch(
        "chutes_miner.api.k8s.operator.uuid.uuid4", return_value=mock_deployment_db.deployment_id
    ):
        result, created_deployment = await k8s.deploy_chute(
            sample_chute, sample_server
        )

    # Assertions
    assert mock_db_session.add.call_count == 1
    assert mock_db_session.commit.call_count == 2
    mock_k8s_core_client.create_namespaced_service.assert_called_once()
    mock_k8s_batch_client.create_namespaced_job.assert_called_once()
    assert result == mock_deployment_db
    assert created_deployment == mock_deployment
    assert mock_deployment_db.host == sample_server.ip_address
    assert mock_deployment_db.port == 30000
    assert mock_deployment_db.stub is False


@pytest.mark.asyncio
async def test_deploy_chute_no_gpu_capacity(sample_server, sample_chute, mock_db_session):
    """Test deployment failure when server doesn't have enough GPU capacity."""
    # Modify server to have no available GPUs
    for gpu in sample_server.gpus:
        gpu.verified = False

    # Setup session mock for deployment retrieval
    mock_deployment_db = MagicMock(spec=Deployment)
    mock_deployment_db.deployment_id = uuid.uuid4()
    mock_result = MagicMock()
    mock_result.unique.return_value = mock_result
    mock_result.scalar_one_or_none.side_effect = [sample_chute, sample_server, mock_deployment_db]
    mock_db_session.execute = AsyncMock(return_value=mock_result)

    # Call the function and expect exception
    with pytest.raises(DeploymentFailure, match="cannot allocate"):
        await k8s.deploy_chute(sample_chute, sample_server)


@pytest.mark.asyncio
async def test_deploy_chute_deployment_disappeared(
    mock_k8s_core_client, mock_k8s_batch_client, mock_db_session, sample_server, sample_chute,
    create_api_test_nodes, create_api_test_pods
):
    """Test handling when deployment disappears mid-flight."""
    # Setup mocks for kubernetes deployment and service creation
    mock_deployment = MagicMock()
    mock_service = MagicMock()
    mock_service.spec.ports = [MagicMock(node_port=30000), MagicMock(node_port=8000), MagicMock(node_port=8001)]

    mock_k8s_batch_client.create_namespaced_job.return_value = mock_deployment
    mock_k8s_core_client.create_namespaced_service.return_value = mock_service

    # Setup session mock to return None for deployment
    # Setup session mock for deployment retrieval
    mock_result = MagicMock()
    mock_result.unique.return_value = mock_result
    mock_result.scalar_one_or_none.side_effect = [sample_chute, sample_server, None]
    mock_db_session.execute = AsyncMock(return_value=mock_result)

    nodes = create_api_test_nodes(1)
    mock_k8s_core_client.read_node.return_value = serializer.deserialize(nodes[0], "V1Node")

    pods = create_api_test_pods(1)
    mock_k8s_core_client.list_namespaced_pod.return_value = V1PodList(items=serializer.deserialize(pods, "list[V1Pod]"))

    # Call the function and expect exception
    with pytest.raises(DeploymentFailure, match="Deployment disappeared mid-flight"):
        await k8s.deploy_chute(sample_chute, sample_server)


@pytest.mark.asyncio
async def test_deploy_chute_api_exception(
    mock_k8s_core_client, mock_k8s_batch_client, mock_db_session, sample_server, sample_chute,
    create_api_test_nodes, create_api_test_pods
):
    """Test handling of API exception during deployment."""
    # Setup mock to raise ApiException
    error = ApiException(status=500, reason="Internal error")
    mock_k8s_batch_client.create_namespaced_job.side_effect = error

    # Setup session mock for deployment retrieval
    mock_deployment_db = MagicMock(spec=Deployment)
    mock_deployment_db.deployment_id = uuid.uuid4()
    mock_result = MagicMock()
    mock_result.unique.return_value = mock_result
    mock_result.scalar_one_or_none.side_effect = [sample_chute, sample_server, mock_deployment_db]
    mock_db_session.execute = AsyncMock(return_value=mock_result)

    # Setup service creation to succeed
    mock_service = MagicMock()
    mock_service.spec.ports = [MagicMock(node_port=30000), MagicMock(node_port=8000), MagicMock(node_port=8001)]
    mock_k8s_core_client.create_namespaced_service.return_value = mock_service

    nodes = create_api_test_nodes(1)
    mock_k8s_core_client.read_node.return_value = serializer.deserialize(nodes[0], "V1Node")

    pods = create_api_test_pods(1)
    mock_k8s_core_client.list_namespaced_pod.return_value = V1PodList(items=serializer.deserialize(pods, "list[V1Pod]"))

    # Call the function and expect exception
    with pytest.raises(DeploymentFailure, match="Failed to deploy chute"):
        await k8s.deploy_chute(sample_chute, sample_server)

    # Verify cleanup was attempted
    mock_k8s_core_client.delete_namespaced_service.assert_called_once()
