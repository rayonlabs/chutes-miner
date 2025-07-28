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
        mock_response.json.side_effect = Exception()
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

        mock_session.patch.return_value.__aenter__ = AsyncMock(return_value=mock_response)
        mock_session.patch.return_value.__aexit__ = AsyncMock(return_value=None)

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

@pytest.fixture(autouse=True)
def mock_sign_request():
    """Mock the sign_request function to return proper format"""
    with patch('chutes_agent.client.sign_request') as mock_sign:
        # Return headers dict and payload dict (not bytes)
        mock_sign.return_value = (
            {"Authorization": "Bearer test-token", "Content-Type": "application/json"},
            {"payload": "data"}
        )
        yield mock_sign

# @pytest.fixture(scope="function")
# def mock_sign_request(mock_module_sign_request):
#     mock_module_sign_request.reset_mock()
#     yield mock_module_sign_request

@pytest.fixture(scope="function")
def control_plane_client():
    """Create ControlPlaneClient instance for testing"""
    from chutes_agent.client import ControlPlaneClient
    return ControlPlaneClient("http://test-control-plane")

@pytest.fixture
def mock_client_class():
    from chutes_agent.client import ControlPlaneClient
    with patch('chutes_agent.monitor.ControlPlaneClient', spec=ControlPlaneClient) as mock_client:
        yield mock_client


@pytest.fixture
def mock_control_plane_client():
    with patch('chutes_agent.monitor.ControlPlaneClient') as mock_class:
        mock_client = AsyncMock()
        mock_class.return_value = mock_client
        yield mock_client

@pytest.fixture
def resource_collector():
    """Create ResourceCollector instance for testing"""
    from chutes_agent.collector import ResourceCollector
    return ResourceCollector()

@pytest_asyncio.fixture
async def resource_monitor(
    mock_batch_client, mock_apps_client, mock_core_client,
    mock_load_k8s_config
):
    """Create ResourceMonitor instance for testing"""
    from chutes_agent.monitor import ResourceMonitor
    monitor = ResourceMonitor()
    yield monitor
    await monitor.stop()