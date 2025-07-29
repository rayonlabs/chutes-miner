from unittest.mock import patch
import pytest

@pytest.fixture(scope="function")
def mock_namespaces(request):
    from chutes_agent.config import settings
    namespaces = getattr(request, 'param', [])
    with patch.object(settings, 'watch_namespaces', namespaces):
        yield