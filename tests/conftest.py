import os
import json
import pytest
from unittest.mock import AsyncMock, MagicMock
from sqlalchemy.ext.asyncio import AsyncSession
from constants import CHUTE_ID, CHUTE_NAME, SERVER_ID, SERVER_NAME, GPU_COUNT


def pytest_configure(config):
    """Set up environment variables before any modules are imported."""
    os.environ["MINER_SS58"] = "5E6xfU3oNU7y1a7pQwoc31fmUjwBZ2gKcNCw8EXsdtCQieUQ"
    os.environ["MINER_SEED"] = "0xe031170f32b4cda05df2f3cf6bc8d7687b683bbce23d9fa960c0b3fc21641b8a"

    validators_json = {
        "supported": [
            {
                "hotkey": "test_validator",
                "registry": "test-registry",
                "api": "http://test-api",
                "socket": "ws://test-socket",
            }
        ]
    }
    os.environ["VALIDATORS"] = json.dumps(validators_json)

    # Print confirmation for debugging
    print("Environment variables set up for testing!")


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
def mock_purge_deployments_response():
    """Mock response from the API."""
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(
        return_value={
            "status": "initiated",
            "deployments_purged": [
                {
                    "chute_id": CHUTE_ID,
                    "chute_name": CHUTE_NAME,
                    "server_id": SERVER_ID,
                    "server_name": SERVER_NAME,
                    "gpu_count": GPU_COUNT,
                }
            ],
        }
    )
    return mock_resp


@pytest.fixture
def mock_purge_deployment_response():
    """Mock response from the API."""
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json = AsyncMock(
        return_value={
            "status": "initiated",
            "deployment_purged": {
                "chute_id": CHUTE_ID,
                "chute_name": CHUTE_NAME,
                "server_id": SERVER_ID,
                "server_name": SERVER_NAME,
                "gpu_count": GPU_COUNT,
            },
        }
    )
    return mock_resp


@pytest.fixture
def mock_db_session():
    """Mock database session."""
    mock_session = AsyncMock(spec=AsyncSession)
    return mock_session


@pytest.fixture
def mock_authorize():
    """Mock authorize dependency."""

    async def _authorize(*args, **kwargs):
        return None

    return _authorize
