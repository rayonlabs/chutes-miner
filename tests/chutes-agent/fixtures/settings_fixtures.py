from unittest.mock import patch
import pytest
from chutes_agent.config import settings

@pytest.fixture(scope="function")
def mock_namespaces(request):
    namespaces = getattr(request, 'param', [])
    with patch.object(settings, 'watch_namespaces', namespaces):
        yield