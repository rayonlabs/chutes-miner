from unittest.mock import AsyncMock

import pytest

from constants import CHUTE_ID, CHUTE_NAME, GPU_COUNT, SERVER_ID, SERVER_NAME

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