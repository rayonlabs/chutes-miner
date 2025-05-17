"""
Unit tests for kubernetes helper module.
"""

from datetime import datetime
from typing import Any, Dict
import uuid
import math
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call
from kubernetes.client.rest import ApiException

from kubernetes.client import (
    V1NodeList,
    V1Node
)

# Import the module under test
from api.deployment.schemas import Deployment
import api.k8s as k8s
from api.exceptions import DeploymentFailure
from api.k8s.constants import SEARCH_DEPLOYMENTS_PATH, SEARCH_NODES_PATH, SEARCH_PODS_PATH
from api.k8s.operator import K8sOperator, KarmadaK8sOperator
from api.config import settings


def get_mock_call_api_side_effect(responses: Dict[str, Any]):
    
  def _mock_call_api(resource_path, method,
                  path_params=None, query_params=None, header_params=None,
                  body=None, post_params=None, files=None,
                  response_type=None, auth_settings=None, async_req=None,
                  _return_http_data_only=None, collection_formats=None,
                  _preload_content=True, _request_timeout=None, _host=None):
          nonlocal responses
          if resource_path in responses:
              response = responses[resource_path]
          else:
              raise RuntimeError(f"No response was provided for path {resource_path}")
          
          return response
          
  return _mock_call_api

def get_api_responses(deployments, pods):
    responses = {}
    if deployments:
      responses[SEARCH_DEPLOYMENTS_PATH] = {
                  'kind': 'DeploymentList',
                  'apiVersion': 'v1',
                  'items': deployments
              }
    if pods:
      responses[SEARCH_PODS_PATH] = {
                  'kind': 'PodList',
                  'apiVersion': 'v1',
                  'items': pods
              }
    return responses

@pytest.fixture(autouse=True, scope="function")
def mock_karmada_k8s_operator():
    # Save the original __new__ method
    original_new = K8sOperator.__new__
    
    # Create a mock implementation that always returns KarmadaK8sOperator
    def mock_new(cls, *args, **kwargs):
        return super(K8sOperator, cls).__new__(KarmadaK8sOperator)
    
    # Apply the mock
    K8sOperator.__new__ = mock_new
    
    # Clear any singleton instance that might exist
    K8sOperator._instance = None
    
    yield
    
    # Restore the original method after test
    K8sOperator.__new__ = original_new
    K8sOperator._instance = None

# Tests for get_kubernetes_nodes
@pytest.mark.asyncio
async def test_get_kubernetes_nodes_success(mock_k8s_api_client):
    """Test successful retrieval of kubernetes nodes."""
    # Setup mock response
    mock_k8s_api_client.call_api.return_value = {
        'kind': 'NodeList',
        'apiVersion': 'v1',
        'items': [
            {
                'metadata': {
                    'name': "node1",
                    'labels': {
                        "chutes/validator": "TEST123",
                        "chutes/external-ip": "192.168.1.100",
                        "nvidia.com/gpu.memory": "16384"
                    },
                    "uid": "node1-uid"
                },
                "status": {
                    "phase": "Ready",
                    "capacity": {
                        "cpu": "8",
                        "memory": "32Gi",
                        "nvidia.com/gpu": "2"
                    }
                }
            }
        ]
    }
    
    # Call the function
    # k8s_core_client.cache_clear()
    result = await k8s.get_kubernetes_nodes()
    
    # Assertions
    mock_k8s_api_client.call_api.assert_called_once_with(
        SEARCH_NODES_PATH,
        "GET",
        query_params={},
        response_type='object',
        _return_http_data_only=True
        # field_selector=None, label_selector="chutes/worker"
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
async def test_get_kubernetes_nodes_exception(mock_k8s_api_client):
    """Test exception handling when retrieving kubernetes nodes."""
    # Setup mock to raise an exception
    mock_k8s_api_client.call_api.side_effect = Exception("API Error")
    
    # Call the function and expect exception
    with pytest.raises(Exception, match="API Error"):
        await k8s.get_kubernetes_nodes()


# Tests for is_deployment_ready
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
def test_extract_deployment_info(mock_k8s_api_client, create_api_test_pods):
    """Test extracting deployment info from k8s deployment object."""
    # Setup mock deployment
    deployment = MagicMock()
    deployment.metadata.uid = "test-uid"
    deployment.metadata.name = "test-deployment"
    deployment.metadata.namespace = "test-namespace"
    deployment.metadata.labels = {
        "chutes/deployment-id": "test-deployment-id",
        "chutes/chute-id": "test-chute-id",
        "chutes/version": "1.0.0"
    }
    deployment.spec.template.spec.node_selector = {"key": "value"}
    deployment.spec.selector.match_labels = {"app": "test"}
    
    # Setup is_deployment_ready mock
    deployment.status.available_replicas = 1
    deployment.status.ready_replicas = 1
    deployment.status.updated_replicas = 1
    deployment.spec.replicas = 1

    pods = create_api_test_pods(1, "chutes")
    
    mock_k8s_api_client.call_api.return_value = {
        'kind': 'PodsList',
        'apiVersion': 'v1',
        'items': pods
    }

    result = k8s.K8sOperator()._extract_deployment_info(deployment)

    mock_k8s_api_client.call_api.assert_called_once_with(
        SEARCH_PODS_PATH,
        "GET",
        query_params={
            "fieldSelector": f"metadata.namespace={deployment.metadata.namespace}",
            "labelSelector": f"app=test"
        },
        response_type='object',
        _return_http_data_only=True
    )


    pod=pods[0]    
    # Assertions
    assert result["uuid"] == deployment.metadata.uid
    assert result["deployment_id"] == deployment.metadata.labels.get("chutes/deployment-id")
    assert result["name"] == deployment.metadata.name
    assert result["namespace"] == deployment.metadata.namespace
    assert result["chute_id"] == deployment.metadata.labels.get("chutes/chute-id")
    assert result["version"] == deployment.metadata.labels.get("chutes/version")
    assert result["ready"] is True
    assert result["node"] == pod["spec"]["nodeName"]

    assert len(result["pods"]) == len(pods)
    assert result["pods"][0]["name"] == pod["metadata"]["name"]
    assert result["pods"][0]["phase"] == pod["status"]["phase"]
    assert result["pods"][0]["restart_count"] == pod["status"]["containerStatuses"][0]["restartCount"]
    if "started_at" in result["pods"][0]["state"]["running"] or "startedAt" in pod["status"]["containerStatuses"][0]["state"]["running"]:  
      assert result["pods"][0]["state"]["running"]["started_at"].timestamp() == datetime.fromisoformat(pod["status"]["containerStatuses"][0]["state"]["running"]["startedAt"]).timestamp()
    if result["pods"][0]["last_state"]["terminated"] or pod["status"]["containerStatuses"][0]["lastState"]["terminated"]:  
      result_terminated = result["pods"][0]["last_state"]["terminated"]
      pod_terminated = pod["status"]["containerStatuses"][0]["lastState"]["terminated"]
      assert result_terminated["exit_code"] == pod_terminated["exitCode"]
      assert result_terminated["reason"] == pod_terminated["reason"]
      assert result_terminated["started_at"].timestamp() == datetime.fromisoformat(pod_terminated["startedAt"]).timestamp()
      assert result_terminated["finished_at"].timestamp() == datetime.fromisoformat(pod_terminated["finishedAt"]).timestamp()


# Tests for get_deployment
@pytest.mark.asyncio
async def test_get_deployment(mock_k8s_api_client, create_api_test_deployments, create_api_test_pods):
    """Test getting a single deployment by ID."""
    deployments=create_api_test_deployments(1)
    pods = create_api_test_pods(1)
    responses = get_api_responses(deployments, pods)

    mock_k8s_api_client.call_api.side_effect = get_mock_call_api_side_effect(responses)

    # Call the function
    deployment_name = deployments[0]["metadata"]["name"]
    result = await k8s.get_deployment(deployment_name)
    
    # Assertions
    api_calls = [
        call(
          SEARCH_DEPLOYMENTS_PATH,
          "GET",
          query_params={
              "fieldSelector": f"metadata.namespace={settings.namespace},metadata.name=chute-{deployment_name}"
          },
          response_type='object',
          _return_http_data_only=True
        ),
        call(
          SEARCH_PODS_PATH,
          "GET",
          query_params={
              "fieldSelector": f"metadata.namespace={deployments[0]["metadata"]["namespace"]}",
              "labelSelector": f"app={deployments[0]["metadata"]["name"]}"
          },
          response_type='object',
          _return_http_data_only=True
        )
    ]
    mock_k8s_api_client.call_api.assert_has_calls(api_calls)

    deployment = deployments[0]
    pod=pods[0] 
    
    assert result["uuid"] == deployment["metadata"]["uid"]
    assert result["deployment_id"] == deployment["metadata"]["labels"].get("chutes/deployment-id")
    assert result["name"] == deployment["metadata"]["name"]
    assert result["namespace"] == deployment["metadata"]["namespace"]
    assert result["chute_id"] == deployment["metadata"]["labels"].get("chutes/chute-id")
    assert result["version"] == deployment["metadata"]["labels"].get("chutes/version")
    assert result["ready"] is True
    assert result["node"] == pod["spec"]["nodeName"]

    assert len(result["pods"]) == len(pods)
    assert result["pods"][0]["name"] == pod["metadata"]["name"]
    assert result["pods"][0]["phase"] == pod["status"]["phase"]
    assert result["pods"][0]["restart_count"] == pod["status"]["containerStatuses"][0]["restartCount"]
    if "started_at" in result["pods"][0]["state"]["running"] or "startedAt" in pod["status"]["containerStatuses"][0]["state"]["running"]:  
      assert result["pods"][0]["state"]["running"]["started_at"].timestamp() == datetime.fromisoformat(pod["status"]["containerStatuses"][0]["state"]["running"]["startedAt"]).timestamp()
    if result["pods"][0]["last_state"]["terminated"] or pod["status"]["containerStatuses"][0]["lastState"]["terminated"]:  
      result_terminated = result["pods"][0]["last_state"]["terminated"]
      pod_terminated = pod["status"]["containerStatuses"][0]["lastState"]["terminated"]
      assert result_terminated["exit_code"] == pod_terminated["exitCode"]
      assert result_terminated["reason"] == pod_terminated["reason"]
      assert result_terminated["started_at"].timestamp() == datetime.fromisoformat(pod_terminated["startedAt"]).timestamp()
      assert result_terminated["finished_at"].timestamp() == datetime.fromisoformat(pod_terminated["finishedAt"]).timestamp()


# Tests for get_deployed_chutes
@pytest.mark.asyncio
async def test_get_deployed_chutes(mock_k8s_api_client, create_api_test_deployments, create_api_test_pods):
    """Test getting all deployed chutes."""
    # Setup mock
    deployments=create_api_test_deployments(1)
    pods = create_api_test_pods(1)
    responses = get_api_responses(deployments, pods)

    mock_k8s_api_client.call_api.side_effect = get_mock_call_api_side_effect(responses)
    
    # Call the function
    deployment_name = deployments[0]["metadata"]["name"]
    results = await k8s.get_deployed_chutes()
    
    # Assertions
    api_calls = [
        call(
          SEARCH_DEPLOYMENTS_PATH,
          "GET",
          query_params={
              "fieldSelector": f"metadata.namespace={settings.namespace}",
              "labelSelector": "chutes/chute=true"
          },
          response_type='object',
          _return_http_data_only=True
        ),
        call(
          SEARCH_PODS_PATH,
          "GET",
          query_params={
              "fieldSelector": f"metadata.namespace={deployments[0]["metadata"]["namespace"]}",
              "labelSelector": f"app={deployments[0]["metadata"]["name"]}"
          },
          response_type='object',
          _return_http_data_only=True
        )
    ]
    mock_k8s_api_client.call_api.assert_has_calls(api_calls)

    result = results[0]
    deployment = deployments[0]
    pod=pods[0] 
    
    assert result["uuid"] == deployment["metadata"]["uid"]
    assert result["deployment_id"] == deployment["metadata"]["labels"].get("chutes/deployment-id")
    assert result["name"] == deployment["metadata"]["name"]
    assert result["namespace"] == deployment["metadata"]["namespace"]
    assert result["chute_id"] == deployment["metadata"]["labels"].get("chutes/chute-id")
    assert result["version"] == deployment["metadata"]["labels"].get("chutes/version")
    assert result["ready"] is True
    assert result["node"] == pod["spec"]["nodeName"]

    assert len(result["pods"]) == len(pods)
    assert result["pods"][0]["name"] == pod["metadata"]["name"]
    assert result["pods"][0]["phase"] == pod["status"]["phase"]
    assert result["pods"][0]["restart_count"] == pod["status"]["containerStatuses"][0]["restartCount"]
    if "started_at" in result["pods"][0]["state"]["running"] or "startedAt" in pod["status"]["containerStatuses"][0]["state"]["running"]:  
      assert result["pods"][0]["state"]["running"]["started_at"].timestamp() == datetime.fromisoformat(pod["status"]["containerStatuses"][0]["state"]["running"]["startedAt"]).timestamp()
    if result["pods"][0]["last_state"]["terminated"] or pod["status"]["containerStatuses"][0]["lastState"]["terminated"]:  
      result_terminated = result["pods"][0]["last_state"]["terminated"]
      pod_terminated = pod["status"]["containerStatuses"][0]["lastState"]["terminated"]
      assert result_terminated["exit_code"] == pod_terminated["exitCode"]
      assert result_terminated["reason"] == pod_terminated["reason"]
      assert result_terminated["started_at"].timestamp() == datetime.fromisoformat(pod_terminated["startedAt"]).timestamp()
      assert result_terminated["finished_at"].timestamp() == datetime.fromisoformat(pod_terminated["finishedAt"]).timestamp()


# Tests for delete_code
@pytest.mark.asyncio
async def test_delete_code_success(mock_k8s_core_client, mock_k8s_custom_objects_client):
    """Test successful deletion of code configmap."""
    # Call the function
    await k8s.delete_code("test-chute-id", "1.0.0")
    
    # Assertions
    mock_k8s_core_client.delete_namespaced_config_map.assert_called_once()
    # Verify the name is based on the UUID generated from chute_id and version
    assert "chute-code-" in mock_k8s_core_client.delete_namespaced_config_map.call_args[1]["name"]
    mock_k8s_custom_objects_client.delete_namespaced_custom_object.assert_called_once()
    assert mock_k8s_custom_objects_client.delete_namespaced_custom_object.call_args[1]["plural"] == "propagationpolicies"

@pytest.mark.asyncio
async def test_delete_code_not_found(mock_k8s_core_client, mock_k8s_custom_objects_client):
    """Test handling of 404 error when deleting configmap."""
    # Setup mock to raise ApiException with 404
    error = ApiException(status=404)
    mock_k8s_core_client.delete_namespaced_config_map.side_effect = error
    
    # Call the function - should not raise exception
    await k8s.delete_code("test-chute-id", "1.0.0")
    
    # Assertions
    mock_k8s_core_client.delete_namespaced_config_map.assert_called_once()
    mock_k8s_custom_objects_client.delete_namespaced_custom_object.assert_called_once()
    assert mock_k8s_custom_objects_client.delete_namespaced_custom_object.call_args[1]["plural"] == "propagationpolicies"

@pytest.mark.asyncio
async def test_delete_code_other_error(mock_k8s_core_client, mock_k8s_custom_objects_client):
    """Test handling of non-404 error when deleting configmap."""
    # Setup mock to raise ApiException with 500
    error = ApiException(status=500)
    mock_k8s_core_client.delete_namespaced_config_map.side_effect = error
    
    # Call the function and expect exception
    with pytest.raises(ApiException):
        await k8s.delete_code("test-chute-id", "1.0.0")


# Tests for wait_for_deletion
@pytest.mark.asyncio
async def test_wait_for_deletion_no_pods(mock_k8s_api_client):
    """Test wait_for_deletion when no pods match the label."""
    # Setup mock to return empty list
    pod_list = MagicMock()
    pod_list.items = []
    mock_k8s_api_client.call_api.return_value = {
                  'kind': 'PodList',
                  'apiVersion': 'v1',
                  'items': []
              }
    
    # Call the function
    await k8s.wait_for_deletion("app=test")
    
    # Assertions
    mock_k8s_api_client.call_api.assert_called_once()

@pytest.mark.asyncio
async def test_wait_for_deletion_with_pods(mock_k8s_api_client, mock_watch, create_api_test_pods):
    """Test wait_for_deletion when pods exist and then get deleted."""
    # Setup mock to return pods initially, then empty
    pods = create_api_test_pods(1)
    
    mock_k8s_api_client.call_api.side_effect = [
        {
            'kind': 'PodList',
            'apiVersion': 'v1',
            'items': pods
        },  # Initial check - pods exist
        {
            'kind': 'PodList',
            'apiVersion': 'v1',
            'items': []
        }       # Check in the watch loop - pods gone
    ]
    
    # Setup watch to return one event
    mock_watch.stream.return_value = [{"type": "DELETED"}]
    
    # Call the function
    await k8s.wait_for_deletion("app=test")
    
    # Assertions
    assert mock_k8s_api_client.call_api.call_count == 2
    mock_watch.stream.assert_called_once()
    mock_watch.stop.assert_called_once()


# Tests for undeploy
@pytest.mark.asyncio
async def test_undeploy_success(mock_k8s_core_client, mock_k8s_app_client, mock_k8s_custom_objects_client):
    """Test successful undeployment of a chute."""
    # Setup mocks
    with patch("api.k8s.operator.K8sOperator.wait_for_deletion") as mock_wait:
        # Call the function
        await k8s.undeploy("test-deployment-id")
        
        # Assertions
        mock_k8s_core_client.delete_namespaced_service.assert_called_once()
        mock_k8s_app_client.delete_namespaced_deployment.assert_called_once()
        mock_wait.assert_called_once()
        assert mock_k8s_custom_objects_client.delete_namespaced_custom_object.call_count == 2

@pytest.mark.asyncio
async def test_undeploy_with_service_error(mock_k8s_core_client, mock_k8s_app_client, mock_k8s_custom_objects_client):
    """Test undeployment when service deletion fails."""
    # Setup service deletion to fail
    mock_k8s_core_client.delete_namespaced_service.side_effect = Exception("Service error")
    
    # Setup remaining mocks
    with patch("api.k8s.operator.K8sOperator.wait_for_deletion") as mock_wait:
        # Call the function - should not raise exception
        await k8s.undeploy("test-deployment-id")
        
        # Assertions
        mock_k8s_core_client.delete_namespaced_service.assert_called_once()
        mock_k8s_app_client.delete_namespaced_deployment.assert_called_once()
        mock_wait.assert_called_once()
        assert mock_k8s_custom_objects_client.delete_namespaced_custom_object.call_count == 2


# Tests for create_code_config_map
@pytest.mark.asyncio
async def test_create_code_config_map_success(mock_k8s_core_client, mock_k8s_custom_objects_client):
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

    # mock_k8s_custom_objects_client.create_namespaced_custom_object.assert_called_once()
    # assert mock_k8s_custom_objects_client.create_namespaced_custom_object.call_args[1]["plural"] == "propagationpolicies"

@pytest.mark.asyncio
async def test_create_code_config_map_conflict(mock_k8s_core_client, mock_k8s_custom_objects_client):
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

    # Check configmap data
    called_config_map = mock_k8s_core_client.create_namespaced_config_map.call_args[1]["body"]
    assert called_config_map.data["app.py"] == "print('Hello World')"


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
async def test_deploy_chute_success(mock_k8s_core_client, mock_k8s_app_client, mock_k8s_custom_objects_client, mock_db_session, sample_server, sample_chute):
    """Test successful deployment of a chute."""
    # Setup mocks for kubernetes deployment and service creation
    mock_deployment = MagicMock()
    mock_service = MagicMock()
    mock_service.spec.ports = [MagicMock(node_port=30000)]
    
    mock_k8s_app_client.create_namespaced_deployment.return_value = mock_deployment
    mock_k8s_core_client.create_namespaced_service.return_value = mock_service
    
    # Setup session mock for deployment retrieval
        # Setup session mock for deployment retrieval
    mock_deployment_db = MagicMock(spec=Deployment)
    mock_deployment_db.deployment_id = uuid.uuid4()
    mock_result = MagicMock()
    mock_result.unique.return_value = mock_result
    mock_result.scalar_one_or_none.side_effect = [
        sample_chute,
        sample_server,
        mock_deployment_db
    ]
    mock_db_session.execute = AsyncMock(return_value=mock_result)
    
    # Call the function
    with patch("api.k8s.operator.uuid.uuid4", return_value=mock_deployment_db.deployment_id):
        result, created_deployment, created_service = await k8s.deploy_chute(sample_chute, sample_server)
    
    # Assertions
    assert mock_db_session.add.call_count == 1
    assert mock_db_session.commit.call_count == 2
    mock_k8s_core_client.create_namespaced_service.assert_called_once()
    mock_k8s_app_client.create_namespaced_deployment.assert_called_once()
    assert result == mock_deployment_db
    assert created_deployment == mock_deployment
    assert created_service == mock_service
    assert mock_deployment_db.host == sample_server.ip_address
    assert mock_deployment_db.port == 30000
    assert mock_deployment_db.stub is False

    mock_k8s_custom_objects_client.create_namespaced_custom_object.call_count == 3
    for call in mock_k8s_custom_objects_client.create_namespaced_custom_object.mock_calls:
      assert call[2]["plural"] == "propagationpolicies"


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
    mock_result.scalar_one_or_none.side_effect = [
        sample_chute,
        sample_server,
        mock_deployment_db
    ]
    mock_db_session.execute = AsyncMock(return_value=mock_result)

    # Call the function and expect exception
    with pytest.raises(DeploymentFailure, match="cannot allocate"):
        await k8s.deploy_chute(sample_chute, sample_server)

@pytest.mark.asyncio
async def test_deploy_chute_deployment_disappeared(mock_k8s_core_client, mock_k8s_app_client, mock_k8s_custom_objects_client, mock_db_session, sample_server, sample_chute):
    """Test handling when deployment disappears mid-flight."""
    # Setup mocks for kubernetes deployment and service creation
    mock_deployment = MagicMock()
    mock_service = MagicMock()
    mock_service.spec.ports = [MagicMock(node_port=30000)]
    
    mock_k8s_app_client.create_namespaced_deployment.return_value = mock_deployment
    mock_k8s_core_client.create_namespaced_service.return_value = mock_service
    
    # Setup session mock to return None for deployment
    # Setup session mock for deployment retrieval
    mock_result = MagicMock()
    mock_result.unique.return_value = mock_result
    mock_result.scalar_one_or_none.side_effect = [
        sample_chute,
        sample_server,
        None
    ]
    mock_db_session.execute = AsyncMock(return_value=mock_result)
    
    # Call the function and expect exception
    with pytest.raises(DeploymentFailure, match="Deployment disappeared mid-flight"):
        await k8s.deploy_chute(sample_chute, sample_server)

    mock_k8s_custom_objects_client.create_namespaced_custom_object.call_count == 3
    for call in mock_k8s_custom_objects_client.create_namespaced_custom_object.mock_calls:
      assert call[2]["plural"] == "propagationpolicies"

    # Add assertions for PP cleanup

@pytest.mark.asyncio
async def test_deploy_chute_api_exception(mock_k8s_core_client, mock_k8s_app_client, mock_k8s_custom_objects_client, mock_db_session, sample_server, sample_chute):
    """Test handling of API exception during deployment."""
    # Setup mock to raise ApiException
    error = ApiException(status=500, reason="Internal error")
    mock_k8s_app_client.create_namespaced_deployment.side_effect = error
    
    # Setup session mock for deployment retrieval
    mock_deployment_db = MagicMock(spec=Deployment)
    mock_deployment_db.deployment_id = uuid.uuid4()
    mock_result = MagicMock()
    mock_result.unique.return_value = mock_result
    mock_result.scalar_one_or_none.side_effect = [
        sample_chute,
        sample_server,
        mock_deployment_db
    ]
    mock_db_session.execute = AsyncMock(return_value=mock_result)

    # Setup service creation to succeed
    mock_service = MagicMock()
    mock_service.spec.ports = [MagicMock(node_port=30000)]
    mock_k8s_core_client.create_namespaced_service.return_value = mock_service
    
    # Call the function and expect exception
    with pytest.raises(DeploymentFailure, match="Failed to deploy chute"):
        await k8s.deploy_chute(sample_chute, sample_server)
    
    # Verify cleanup was attempted
    mock_k8s_core_client.delete_namespaced_service.assert_called_once()
    mock_k8s_custom_objects_client.delete_namespaced_custom_object.call_count = 3

