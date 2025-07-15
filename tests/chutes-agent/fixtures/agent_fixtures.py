from collections import namedtuple
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest_asyncio

@pytest.fixture(scope="function")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

@pytest.fixture(scope="function")
def mock_k8s_client():
    """Mock kubernetes_asyncio client"""
    mock_client = MagicMock()
    mock_client.CoreV1Api = MagicMock()
    mock_client.AppsV1Api = MagicMock()
    return mock_client

MockHTTPComponents = namedtuple('MockHTTPComponents', ['client_session', 'session', 'response'])

@pytest.fixture(scope="function")
def mock_aiohttp_session():
    """Mock aiohttp session"""
    with patch("aiohttp.ClientSession") as mock_client_session:
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.text=AsyncMock(return_value="Success")

        mock_session = MagicMock()
        mock_session.post.return_value.__aenter__ = AsyncMock(return_value=mock_response)
        mock_session.post.return_value.__aexit__ = AsyncMock(return_value=None)

        mock_session.get.return_value.__aenter__ = AsyncMock(return_value=mock_response)
        mock_session.get.return_value.__aexit__ = AsyncMock(return_value=None)

        mock_session.put.return_value.__aenter__ = AsyncMock(return_value=mock_response)
        mock_session.put.return_value.__aexit__ = AsyncMock(return_value=None)

        mock_session.delete.return_value.__aenter__ = AsyncMock(return_value=mock_response)
        mock_session.delete.return_value.__aexit__ = AsyncMock(return_value=None)

        mock_client_session.return_value = mock_session            
        mock_client_session.return_value.__aenter__.return_value = mock_session
        mock_client_session.return_value.__aexit__.return_value = None

        print(mock_client_session)
        print(mock_session)
        print(mock_response)

        yield MockHTTPComponents(
            client_session=mock_client_session,
            session=mock_session,
            response=mock_response
        )

@pytest.fixture(scope="module")
def mock_module_sign_request():
    """Mock the sign_request function to return proper format"""
    with patch('chutes_agent.client.sign_request') as mock_sign:
        # Return headers dict and payload dict (not bytes)
        mock_sign.return_value = (
            {"Authorization": "Bearer test-token", "Content-Type": "application/json"},
            {"signed": "payload"}
        )
        yield mock_sign

@pytest.fixture(scope="function")
def mock_sign_request(mock_module_sign_request):
    mock_module_sign_request.reset_mock()
    yield mock_module_sign_request

@pytest.fixture(scope="function")
def sample_pod():
    """Sample kubernetes_asyncio pod object"""
    pod = MagicMock()
    pod.metadata.name = "test-pod"
    pod.metadata.namespace = "default"
    pod.to_dict.return_value = {
        "metadata": {"name": "test-pod", "namespace": "default"},
        "spec": {"containers": [{"name": "test-container"}]}
    }
    return pod

@pytest.fixture(scope="function")
def sample_deployment():
    """Sample kubernetes_asyncio deployment object"""
    deployment = MagicMock()
    deployment.metadata.name = "test-deployment"
    deployment.metadata.namespace = "default"
    deployment.to_dict.return_value = {
        "metadata": {"name": "test-deployment", "namespace": "default"},
        "spec": {"replicas": 3}
    }
    return deployment

@pytest.fixture(scope="function")
def sample_service():
    """Sample kubernetes_asyncio service object"""
    service = MagicMock()
    service.metadata.name = "test-service"
    service.metadata.namespace = "default"
    service.to_dict.return_value = {
        "metadata": {"name": "test-service", "namespace": "default"},
        "spec": {"ports": [{"port": 80}]}
    }
    return service

@pytest.fixture(scope="function")
def control_plane_client():
    """Create ControlPlaneClient instance for testing"""
    from chutes_agent.client import ControlPlaneClient
    return ControlPlaneClient("http://test-control-plane")

@pytest.fixture(scope="module")
def mock_module_client_class():
    with patch('chutes_agent.monitor.ControlPlaneClient') as mock_client:
        yield mock_client

@pytest.fixture(scope="function")
def mock_client_class(mock_module_client_class):
    mock_module_client_class.reset_mock()
    yield mock_module_client_class

@pytest.fixture(scope="function")
def resource_collector():
    """Create ResourceCollector instance for testing"""
    from chutes_agent.collector import ResourceCollector
    return ResourceCollector()

@pytest_asyncio.fixture(scope="function")
async def resource_monitor():
    """Create ResourceMonitor instance for testing"""
    from chutes_agent.monitor import ResourceMonitor
    monitor = ResourceMonitor()
    yield monitor
    await monitor.stop()