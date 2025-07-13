from chutes_monitor.cluster_monitor import HealthChecker
import pytest


@pytest.fixture(autouse=True)
def reset_health_checker_singleton():
    """Reset HealthChecker singleton before each test"""
    # Clear the singleton instance
    HealthChecker._instance = None
    yield
    # Optionally clean up after test
    HealthChecker._instance = None