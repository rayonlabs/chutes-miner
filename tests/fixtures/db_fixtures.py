from unittest.mock import AsyncMock, patch
import pytest

@pytest.fixture
def mock_session():
    
    
    # Create a list of paths where k8s_core_client is imported
    import_paths = [
        "api.k8s.get_session",
        "api.k8s.operator.get_session"
    ]

    # Create a specific __aexit__ function that returns False only when an exception is raised
    async def mock_aexit(self, exc_type, exc_val, exc_tb):
        # Return False only if there's an exception (exc_type is not None)
        # Otherwise return True for normal operation
        return exc_type is None
    
    session = AsyncMock()

    mock_get_session = AsyncMock(
            __aenter__=AsyncMock(return_value=session),
            __aexit__=mock_aexit
        )
    
    # Create and start patches for each import path, all returning the same mock
    patches = []
    for path in import_paths:
        patcher = patch(path, return_value=mock_get_session)
        patcher.start()
        patches.append(patcher)
    
    # Yield the shared mock for use in tests
    yield session
    
    # Stop all patches when done
    for patcher in patches:
        patcher.stop()