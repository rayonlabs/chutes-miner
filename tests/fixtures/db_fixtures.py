from unittest.mock import AsyncMock, patch
import pytest

@pytest.fixture
def mock_session():
    session = AsyncMock()
    
    # Create a specific __aexit__ function that returns False only when an exception is raised
    async def mock_aexit(self, exc_type, exc_val, exc_tb):
        # Return False only if there's an exception (exc_type is not None)
        # Otherwise return True for normal operation
        return exc_type is None
    
    with patch(
        "api.k8s.get_session", 
        return_value=AsyncMock(
            __aenter__=AsyncMock(return_value=session),
            __aexit__=mock_aexit
        )
    ):
        yield session