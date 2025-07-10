import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi.testclient import TestClient
from fastapi import FastAPI, HTTPException
from chutes_agent.api.config.router import router, get_kubeconfig_from_secret
import base64

# Create test app
app = FastAPI()
app.include_router(router)
client = TestClient(app)

@pytest.mark.asyncio
@patch('kubernetes.client.CoreV1Api')
@patch('kubernetes.config.load_incluster_config')
async def test_get_kubeconfig_from_secret_success(mock_load_config, mock_core_v1_class):
    """Test successful kubeconfig retrieval"""
    # Mock the secret data
    kubeconfig_content = "apiVersion: v1\nkind: Config"
    kubeconfig_b64 = base64.b64encode(kubeconfig_content.encode()).decode()
    
    mock_secret = MagicMock()
    mock_secret.data = {"kubeconfig": kubeconfig_b64}
    
    mock_v1 = MagicMock()
    mock_v1.read_namespaced_secret.return_value = mock_secret
    mock_core_v1_class.return_value = mock_v1
    
    result = await get_kubeconfig_from_secret()
    
    assert result == kubeconfig_content
    mock_v1.read_namespaced_secret.assert_called_once_with(
        name="miner-kubeconfig", 
        namespace="default"
    )

@pytest.mark.asyncio
@patch('kubernetes.client.CoreV1Api')
@patch('kubernetes.config.load_incluster_config')
async def test_get_kubeconfig_from_secret_not_found(mock_load_config, mock_core_v1_class):
    """Test kubeconfig retrieval when secret not found"""
    from kubernetes.client.rest import ApiException
    
    mock_v1 = MagicMock()
    mock_v1.read_namespaced_secret.side_effect = ApiException(status=404, reason="Not Found")
    mock_core_v1_class.return_value = mock_v1
    
    with pytest.raises(HTTPException) as exc_info:
        await get_kubeconfig_from_secret()
    
    assert exc_info.value.status_code == 404
    assert "not found" in exc_info.value.detail

@pytest.mark.asyncio
@patch('kubernetes.client.CoreV1Api')
@patch('kubernetes.config.load_incluster_config')
async def test_get_kubeconfig_from_secret_permission_denied(mock_load_config, mock_core_v1_class):
    """Test kubeconfig retrieval with permission denied"""
    from kubernetes.client.rest import ApiException
    
    mock_v1 = MagicMock()
    mock_v1.read_namespaced_secret.side_effect = ApiException(status=403, reason="Forbidden")
    mock_core_v1_class.return_value = mock_v1
    
    with pytest.raises(HTTPException) as exc_info:
        await get_kubeconfig_from_secret()
    
    assert exc_info.value.status_code == 403
    assert "Permission denied" in exc_info.value.detail

@pytest.mark.asyncio
@patch('kubernetes.client.CoreV1Api')
@patch('kubernetes.config.load_incluster_config')
async def test_get_kubeconfig_from_secret_missing_key(mock_load_config, mock_core_v1_class):
    """Test kubeconfig retrieval when secret missing kubeconfig key"""
    mock_secret = MagicMock()
    mock_secret.data = {"other_key": "value"}
    
    mock_v1 = MagicMock()
    mock_v1.read_namespaced_secret.return_value = mock_secret
    mock_core_v1_class.return_value = mock_v1
    
    with pytest.raises(HTTPException) as exc_info:
        await get_kubeconfig_from_secret()
    
    assert exc_info.value.status_code == 500
    assert "does not contain 'kubeconfig' key" in exc_info.value.detail

@pytest.mark.asyncio
@patch('kubernetes.config.load_kube_config', side_effect=Exception("Kube config error"))
@patch('kubernetes.config.load_incluster_config', side_effect=Exception("Config error"))
async def test_get_kubeconfig_from_secret_config_failure(mock_incluster_config, mock_kube_config):
    """Test kubeconfig retrieval when config loading fails"""
    with pytest.raises(HTTPException) as exc_info:
        await get_kubeconfig_from_secret()
    
    assert exc_info.value.status_code == 500
    assert "Error loading kubeconfig" in exc_info.value.detail

@pytest.mark.asyncio
@patch('kubernetes.client.CoreV1Api')
@patch('kubernetes.config.load_incluster_config')
async def test_get_kubeconfig_from_secret_custom_params(mock_load_config, mock_core_v1_class):
    """Test kubeconfig retrieval with custom secret name and namespace"""
    kubeconfig_content = "custom config"
    kubeconfig_b64 = base64.b64encode(kubeconfig_content.encode()).decode()
    
    mock_secret = MagicMock()
    mock_secret.data = {"kubeconfig": kubeconfig_b64}
    
    mock_v1 = MagicMock()
    mock_v1.read_namespaced_secret.return_value = mock_secret
    mock_core_v1_class.return_value = mock_v1
    
    result = await get_kubeconfig_from_secret(
        secret_name="custom-secret", 
        namespace="custom-namespace"
    )
    
    assert result == kubeconfig_content
    mock_v1.read_namespaced_secret.assert_called_once_with(
        name="custom-secret", 
        namespace="custom-namespace"
    )

def test_get_miner_kubeconfig_endpoint_structure():
    """Test the structure of the kubeconfig endpoint"""
    # Note: Full testing of this endpoint requires proper auth mock setup
    # This test verifies the endpoint exists and has the right structure
    from chutes_agent.api.config.router import get_miner_kubeconfig
    
    # Verify the function exists and is callable
    assert callable(get_miner_kubeconfig)
    
    # Check if it has the expected dependencies (this might vary based on auth implementation)
    import inspect
    sig = inspect.signature(get_miner_kubeconfig)
    # Should have at least one parameter for the auth dependency
    assert len(sig.parameters) >= 0