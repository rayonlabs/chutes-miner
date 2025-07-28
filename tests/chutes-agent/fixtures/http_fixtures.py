from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True, scope='module')
def mock_authorize():
    with patch("chutes_common.auth.authorize") as mock_authorize:
        mock_authorize.return_value = lambda: None  # or whatever it should return
        yield mock_authorize