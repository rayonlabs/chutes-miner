import pytest
import base64
from unittest.mock import Mock, patch, MagicMock
from fastapi.testclient import TestClient
from fastapi import FastAPI
from kubernetes.client.rest import ApiException


@pytest.fixture
def app(mock_auth):
    """Create a FastAPI app with the router for testing"""        
    # Import the router after mocking auth
    from chutes_miner_gpu.api.config.router import router
    
    app = FastAPI()
    app.include_router(router)
    return app


@pytest.fixture
def client(app):
    """Create a test client"""
    return TestClient(app)


@pytest.fixture(scope="function")
def mock_settings():
    """Mock settings - no longer needed for file path but kept for compatibility"""
    with patch('chutes_miner_gpu.api.config.router.settings') as mock_settings:
        yield mock_settings


@pytest.fixture(scope="module")
def mock_auth():
    with patch('chutes_common.auth.authorize') as mock_auth:
        mock_auth.return_value = lambda: None
        yield mock_auth


@pytest.fixture
def mock_k8s_config():
    """Mock Kubernetes configuration loading"""
    with patch('chutes_miner_gpu.api.config.router.config') as mock_config:
        mock_config.load_incluster_config.return_value = None
        mock_config.load_kube_config.return_value = None
        mock_config.ConfigException = Exception
        yield mock_config


@pytest.fixture
def mock_k8s_client():
    """Mock Kubernetes client"""
    with patch('chutes_miner_gpu.api.config.router.client') as mock_client:
        mock_v1 = Mock()
        mock_client.CoreV1Api.return_value = mock_v1
        yield mock_v1


def create_mock_secret(kubeconfig_content: str):
    """Helper function to create a mock secret object"""
    mock_secret = Mock()
    encoded_content = base64.b64encode(kubeconfig_content.encode('utf-8')).decode('utf-8')
    mock_secret.data = {'kubeconfig': encoded_content}
    return mock_secret


def test_successful_kubeconfig_read_from_secret(client, mock_settings, mock_k8s_config, mock_k8s_client):
    """Test successful reading of kubeconfig from secret"""
    kubeconfig_content = """
apiVersion: v1
kind: Config
clusters:
- cluster:
    server: https://test-server.com
  name: test-cluster
"""
    
    mock_secret = create_mock_secret(kubeconfig_content)
    mock_k8s_client.read_namespaced_secret.return_value = mock_secret
    
    response = client.get("/kubeconfig")
    
    assert response.status_code == 200
    assert response.json() == {"kubeconfig": kubeconfig_content}
    
    # Verify the correct secret was requested
    mock_k8s_client.read_namespaced_secret.assert_called_once_with(
        name="miner-credentials",
        namespace="default"
    )


def test_secret_not_found(client, mock_settings, mock_k8s_config, mock_k8s_client):
    """Test when secret doesn't exist"""
    api_exception = ApiException(status=404, reason="Not Found")
    mock_k8s_client.read_namespaced_secret.side_effect = api_exception
    
    response = client.get("/kubeconfig")
    
    assert response.status_code == 404
    assert "Secret miner-credentials not found in namespace default" in response.json()["detail"]


def test_secret_permission_denied(client, mock_settings, mock_k8s_config, mock_k8s_client):
    """Test when there's no permission to read the secret"""
    api_exception = ApiException(status=403, reason="Forbidden")
    mock_k8s_client.read_namespaced_secret.side_effect = api_exception
    
    response = client.get("/kubeconfig")
    
    assert response.status_code == 403
    assert "Permission denied accessing secret miner-credentials" in response.json()["detail"]


def test_secret_missing_kubeconfig_key(client, mock_settings, mock_k8s_config, mock_k8s_client):
    """Test when secret exists but doesn't contain kubeconfig key"""
    mock_secret = Mock()
    mock_secret.data = {'other-key': 'other-value'}
    mock_k8s_client.read_namespaced_secret.return_value = mock_secret
    
    response = client.get("/kubeconfig")
    
    assert response.status_code == 500
    assert "does not contain 'kubeconfig' key" in response.json()["detail"]


def test_kubernetes_config_load_failure(client, mock_settings, mock_k8s_config, mock_k8s_client):
    """Test when Kubernetes configuration cannot be loaded"""
    mock_k8s_config.load_incluster_config.side_effect = Exception("Config error")
    mock_k8s_config.load_kube_config.side_effect = Exception("Config error")
    
    response = client.get("/kubeconfig")
    
    assert response.status_code == 500
    assert "Unable to load Kubernetes configuration" in response.json()["detail"]


def test_kubernetes_api_error(client, mock_settings, mock_k8s_config, mock_k8s_client):
    """Test generic Kubernetes API error"""
    api_exception = ApiException(status=500, reason="Internal Server Error")
    mock_k8s_client.read_namespaced_secret.side_effect = api_exception
    
    response = client.get("/kubeconfig")
    
    assert response.status_code == 500
    assert "Error retrieving secret" in response.json()["detail"]

def test_base64_decode_error(client, mock_settings, mock_k8s_config, mock_k8s_client):
    """Test when base64 decoding fails"""
    mock_secret = Mock()
    mock_secret.data = {'kubeconfig': 'invalid-base64!!!'}
    mock_k8s_client.read_namespaced_secret.return_value = mock_secret
    
    response = client.get("/kubeconfig")
    
    assert response.status_code == 500
    assert "Error loading kubeconfig: Invalid base64-encoded string" in response.json()["detail"]


def test_kubeconfig_with_special_characters(client, mock_settings, mock_k8s_config, mock_k8s_client):
    """Test reading kubeconfig with special characters and unicode"""
    kubeconfig_content = """
apiVersion: v1
kind: Config
# Special characters: àáâãäåæçèéêë
clusters:
- cluster:
    server: https://test-server.com
  name: test-cluster-™
"""
    
    mock_secret = create_mock_secret(kubeconfig_content)
    mock_k8s_client.read_namespaced_secret.return_value = mock_secret
    
    response = client.get("/kubeconfig")
    
    assert response.status_code == 200
    assert response.json() == {"kubeconfig": kubeconfig_content}


def test_empty_kubeconfig_secret(client, mock_settings, mock_k8s_config, mock_k8s_client):
    """Test reading an empty kubeconfig from secret"""
    mock_secret = create_mock_secret("")
    mock_k8s_client.read_namespaced_secret.return_value = mock_secret
    
    response = client.get("/kubeconfig")
    
    assert response.status_code == 200
    assert response.json() == {"kubeconfig": ""}


def test_large_kubeconfig_secret(client, mock_settings, mock_k8s_config, mock_k8s_client):
    """Test reading a large kubeconfig from secret"""
    # Simulate a large kubeconfig with multiple clusters
    large_kubeconfig = """
apiVersion: v1
kind: Config
clusters:
""" + "\n".join([f"""- cluster:
    server: https://cluster-{i}.example.com
  name: cluster-{i}""" for i in range(100)])
    
    mock_secret = create_mock_secret(large_kubeconfig)
    mock_k8s_client.read_namespaced_secret.return_value = mock_secret
    
    response = client.get("/kubeconfig")
    
    assert response.status_code == 200
    assert response.json() == {"kubeconfig": large_kubeconfig}


def test_authorization_dependency_called(client, mock_settings, mock_auth, mock_k8s_config, mock_k8s_client):
    """Test that the authorization dependency is properly called"""
    mock_secret = create_mock_secret("test content")
    mock_k8s_client.read_namespaced_secret.return_value = mock_secret
    
    response = client.get("/kubeconfig")
    
    # Verify authorize was called with correct parameters
    mock_auth.assert_called_once_with(
        allow_validator=True, 
        purpose="management"
    )


def test_in_cluster_config_preferred(client, mock_settings, mock_k8s_config, mock_k8s_client):
    """Test that in-cluster config is tried first"""
    mock_secret = create_mock_secret("test content")
    mock_k8s_client.read_namespaced_secret.return_value = mock_secret
    
    response = client.get("/kubeconfig")
    
    assert response.status_code == 200
    
    # Verify in-cluster config was tried first
    mock_k8s_config.load_incluster_config.assert_called_once()


def test_fallback_to_kube_config(client, mock_settings, mock_k8s_config, mock_k8s_client):
    """Test fallback to regular kube config when in-cluster fails"""
    mock_secret = create_mock_secret("test content")
    mock_k8s_client.read_namespaced_secret.return_value = mock_secret
    
    # Make in-cluster config fail
    mock_k8s_config.load_incluster_config.side_effect = Exception("Not in cluster")
    
    response = client.get("/kubeconfig")
    
    assert response.status_code == 200
    
    # Verify both methods were tried
    mock_k8s_config.load_incluster_config.assert_called_once()
    mock_k8s_config.load_kube_config.assert_called_once()


def test_secret_name_and_namespace_hardcoded(client, mock_settings, mock_k8s_config, mock_k8s_client):
    """Test that secret name and namespace are correctly hardcoded"""
    mock_secret = create_mock_secret("test content")
    mock_k8s_client.read_namespaced_secret.return_value = mock_secret
    
    response = client.get("/kubeconfig")
    
    assert response.status_code == 200
    
    # Verify the exact secret name and namespace were used
    mock_k8s_client.read_namespaced_secret.assert_called_once_with(
        name="miner-credentials",
        namespace="default"
    )


def test_unexpected_exception_handling(client, mock_settings, mock_k8s_config, mock_k8s_client):
    """Test handling of unexpected exceptions"""
    mock_k8s_client.read_namespaced_secret.side_effect = RuntimeError("Unexpected error")
    
    response = client.get("/kubeconfig")
    
    assert response.status_code == 500
    assert "Error loading kubeconfig: Unexpected error" in response.json()["detail"]


def test_utf8_encoding_preserved(client, mock_settings, mock_k8s_config, mock_k8s_client):
    """Test that UTF-8 encoding is preserved through base64 encoding/decoding"""
    kubeconfig_content = "UTF-8 content: 你好世界 🌍"
    
    mock_secret = create_mock_secret(kubeconfig_content)
    mock_k8s_client.read_namespaced_secret.return_value = mock_secret
    
    response = client.get("/kubeconfig")
    
    assert response.status_code == 200
    assert response.json() == {"kubeconfig": kubeconfig_content}


def test_multiple_secret_calls_isolated(client, mock_settings, mock_k8s_config, mock_k8s_client):
    """Test that multiple calls to the endpoint work independently"""
    kubeconfig_content_1 = "first kubeconfig"
    kubeconfig_content_2 = "second kubeconfig"
    
    # First call
    mock_secret_1 = create_mock_secret(kubeconfig_content_1)
    mock_k8s_client.read_namespaced_secret.return_value = mock_secret_1
    
    response_1 = client.get("/kubeconfig")
    assert response_1.status_code == 200
    assert response_1.json() == {"kubeconfig": kubeconfig_content_1}
    
    # Second call with different content
    mock_secret_2 = create_mock_secret(kubeconfig_content_2)
    mock_k8s_client.read_namespaced_secret.return_value = mock_secret_2
    
    response_2 = client.get("/kubeconfig")
    assert response_2.status_code == 200
    assert response_2.json() == {"kubeconfig": kubeconfig_content_2}
    
    # Verify both calls were made
    assert mock_k8s_client.read_namespaced_secret.call_count == 2


def test_api_exception_with_no_status(client, mock_settings, mock_k8s_config, mock_k8s_client):
    """Test API exception without status code"""
    api_exception = ApiException(reason="Unknown error")
    mock_k8s_client.read_namespaced_secret.side_effect = api_exception
    
    response = client.get("/kubeconfig")
    
    assert response.status_code == 500
    assert "Error retrieving secret" in response.json()["detail"]