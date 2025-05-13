from unittest.mock import AsyncMock
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

@pytest.fixture
def mock_db_session():
    """Mock database session."""
    mock_session = AsyncMock(spec=AsyncSession)
    return mock_session