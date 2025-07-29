from unittest.mock import AsyncMock, patch

import aiohttp
import pytest


@pytest.fixture(autouse=True, scope='module')
def mock_authorize():
    with patch("chutes_common.auth.authorize") as mock_authorize:
        mock_authorize.return_value = lambda: None  # or whatever it should return
        yield mock_authorize

# @pytest.fixture(autouse=True)
# def mock_aiohttp_session():
#     """Mock aiohttp.ClientSession to prevent real HTTP requests"""
    
#     # Create a mock session
#     mock_session = AsyncMock(spec=aiohttp.ClientSession)
#     mock_session.closed = False
    
#     # Mock the context managers for HTTP methods
#     mock_response = AsyncMock()
#     mock_response.status = 200
#     mock_response.json = AsyncMock(return_value={})
#     mock_response.text = AsyncMock(return_value="")
    
#     # Create context manager mocks that return the mock response
#     mock_session.post.return_value.__aenter__ = AsyncMock(return_value=mock_response)
#     mock_session.post.return_value.__aexit__ = AsyncMock(return_value=None)
    
#     mock_session.put.return_value.__aenter__ = AsyncMock(return_value=mock_response)
#     mock_session.put.return_value.__aexit__ = AsyncMock(return_value=None)
    
#     mock_session.patch.return_value.__aenter__ = AsyncMock(return_value=mock_response)
#     mock_session.patch.return_value.__aexit__ = AsyncMock(return_value=None)
    
#     mock_session.delete.return_value.__aenter__ = AsyncMock(return_value=mock_response)
#     mock_session.delete.return_value.__aexit__ = AsyncMock(return_value=None)
    
#     mock_session.close = AsyncMock()
    
#     # Patch the ClientSession constructor to return our mock
#     with patch('aiohttp.ClientSession', return_value=mock_session):
#         yield mock_session