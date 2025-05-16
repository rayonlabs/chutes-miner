import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from sqlalchemy.sql.selectable import Select
from fastapi.testclient import TestClient
from fastapi import FastAPI, HTTPException

from api.deployment.router import router, purge, purge_deployment
from api.deployment.schemas import Deployment
from api.server.router import purge_server

# Create test app
app = FastAPI()
app.include_router(router, prefix="/deployments")
client = TestClient(app)


@pytest.fixture
def mock_deployment():
    """Create a mock deployment object."""
    deployment = MagicMock(spec=Deployment)
    deployment.deployment_id = "test-deployment-id"
    deployment.chute_id = "test-chute-id"
    deployment.server_id = "test-server-id"

    # Set up related objects
    deployment.chute = MagicMock()
    deployment.chute.name = "test-chute-name"
    deployment.server = MagicMock()
    deployment.server.name = "test-server-name"
    deployment.gpus = [MagicMock(), MagicMock()]  # Two mock GPUs

    return deployment


@pytest.mark.asyncio
async def test_purge_endpoint(mock_db_session, mock_deployment):
    """Test the purge endpoint."""
    # Set up mock query result
    mock_result = MagicMock()
    mock_result.unique.return_value = mock_result
    mock_result.scalars.return_value = mock_result
    mock_result.all.return_value = [mock_deployment]
    mock_db_session.execute = AsyncMock(return_value=mock_result)

    # Mock Gepetto
    mock_gepetto = MagicMock()
    mock_gepetto.undeploy = AsyncMock()

    with patch("api.deployment.router.Gepetto", return_value=mock_gepetto):
        with patch("api.deployment.router.logger") as mock_logger:
            # Call the function
            response = await purge(db=mock_db_session)

            # Assertions
            assert response["status"] == "initiated"
            assert len(response["deployments_purged"]) == 1
            assert response["deployments_purged"][0]["chute_id"] == "test-chute-id"
            assert response["deployments_purged"][0]["chute_name"] == "test-chute-name"
            assert response["deployments_purged"][0]["server_id"] == "test-server-id"
            assert response["deployments_purged"][0]["server_name"] == "test-server-name"
            assert response["deployments_purged"][0]["gpu_count"] == 2

            # Verify logger was called
            mock_logger.warning.assert_called_once()

            # Verify create_task was called to undeploy
            mock_db_session.execute.assert_called_once()
            # Note: We can't directly verify asyncio.create_task was called because
            # it's a built-in that's hard to mock, but we can verify the gepetto instance
            # and method were called correctly


@pytest.mark.asyncio
async def test_purge_deployment_endpoint(mock_db_session, mock_deployment):
    """Test the purge_deployment endpoint."""
    # Set up mock query result for a single deployment
    mock_result = MagicMock()
    mock_result.unique.return_value = mock_result
    mock_result.scalar_one_or_none.return_value = mock_deployment
    mock_db_session.execute = AsyncMock(return_value=mock_result)

    # Mock Gepetto
    mock_gepetto = MagicMock()
    mock_gepetto.undeploy = AsyncMock()

    with patch("api.deployment.router.Gepetto", return_value=mock_gepetto):
        with patch("api.deployment.router.logger") as mock_logger:
            # Call the function
            response = await purge_deployment(
                deployment_id="test-deployment-id", db=mock_db_session
            )

            # Assertions
            assert response["status"] == "initiated"
            assert response["deployment_purged"] == mock_deployment

            # Verify logger was called
            mock_logger.warning.assert_called_once()

            # Verify db.execute was called with the right query
            mock_db_session.execute.assert_called_once()
            # Get the first positional argument of the first call
            call_args = mock_db_session.execute.call_args[0][0]
            # Check that it's a select query
            assert isinstance(call_args, Select)


@pytest.mark.asyncio
async def test_purge_server_endpoint(mock_db_session, mock_deployment):
    """Test the purge_server endpoint."""
    # Set up mock query result for a single deployment
    mock_result = MagicMock()
    mock_result.unique.return_value = mock_result
    mock_result.scalars.return_value = mock_result
    mock_result.all.return_value = [mock_deployment]
    mock_db_session.execute = AsyncMock(return_value=mock_result)

    # Mock Gepetto
    mock_gepetto = MagicMock()
    mock_gepetto.undeploy = AsyncMock()

    with patch("api.server.router.Gepetto", return_value=mock_gepetto):
        with patch("api.server.router.logger") as mock_logger:
            # Call the function
            response = await purge_server(id_or_name="test-deployment-id", db=mock_db_session)

            # Assertions
            assert response["status"] == "initiated"
            assert len(response["deployments_purged"]) == 1
            assert response["deployments_purged"][0]["chute_id"] == "test-chute-id"
            assert response["deployments_purged"][0]["chute_name"] == "test-chute-name"
            assert response["deployments_purged"][0]["server_id"] == "test-server-id"
            assert response["deployments_purged"][0]["server_name"] == "test-server-name"
            assert response["deployments_purged"][0]["gpu_count"] == 2

            # Verify logger was called
            mock_logger.warning.assert_called_once()

            # Verify db.execute was called with the right query
            mock_db_session.execute.assert_called_once()
            # Get the first positional argument of the first call
            call_args = mock_db_session.execute.call_args[0][0]
            # Check that it's a select query
            assert isinstance(call_args, Select)


@pytest.mark.asyncio
async def test_purge_invalid_deployment_id(mock_db_session):
    """Test purge_deployment with an invalid deployment ID."""
    # Set up mock query result for no deployments
    mock_result = MagicMock()
    mock_result.unique.return_value = mock_result
    mock_result.scalar_one_or_none.return_value = None
    mock_db_session.execute = AsyncMock(return_value=mock_result)

    # Mock Gepetto
    mock_gepetto = MagicMock()

    with patch("api.deployment.router.Gepetto", return_value=mock_gepetto):
        # This should raise an HTTPException because the deployment is None
        with pytest.raises(HTTPException):
            await purge_deployment(deployment_id="nonexistent-id", db=mock_db_session)


@pytest.mark.asyncio
async def test_purge_empty_deployments(mock_db_session):
    """Test purge with no deployments."""
    # Set up mock query result for no deployments
    mock_result = MagicMock()
    mock_result.unique.return_value = mock_result
    mock_result.scalars.return_value = mock_result
    mock_result.all.return_value = []
    mock_db_session.execute = AsyncMock(return_value=mock_result)

    # Mock Gepetto
    mock_gepetto = MagicMock()

    with patch("api.deployment.router.Gepetto", return_value=mock_gepetto):
        # Call the function
        response = await purge(db=mock_db_session)

        # Assertions
        assert response["status"] == "initiated"
        assert len(response["deployments_purged"]) == 0
