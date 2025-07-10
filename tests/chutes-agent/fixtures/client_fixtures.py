from unittest.mock import patch

import pytest
from tenacity import retry, stop_after_attempt, wait_fixed


@pytest.fixture(autouse=True, scope="function")
def fast_retry():
    """Make all retries immediate and single-attempt during tests"""
    def no_retry_decorator(*args, **kwargs):
        # Return a decorator that only tries once with no wait
        return retry(
            stop=stop_after_attempt(1),
            wait=wait_fixed(0),
            reraise=True
        )
    
    with patch('tenacity.retry', no_retry_decorator):
        yield