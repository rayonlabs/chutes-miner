import json
from unittest.mock import AsyncMock, MagicMock
import pytest


@pytest.fixture
def mock_hotkey_content():
    """Mock content of the hotkey file."""
    return json.dumps(
        {
            "ss58Address": "test_miner_address",
            "secretSeed": "0xe031170f32b4cda05df2f3cf6bc8d7687b683bbce23d9fa960c0b3fc21641b8a",
        }
    )

@pytest.fixture
def mock_client_session():
    """Mock aiohttp ClientSession for testing."""

    def _session_factory(mock_response):
        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)

        mock_delete_cm = MagicMock()
        mock_delete_cm.__aenter__ = AsyncMock(return_value=mock_response)
        mock_delete_cm.__aexit__ = AsyncMock(return_value=None)
        mock_session.delete = MagicMock(return_value=mock_delete_cm)

        return mock_session

    return _session_factory