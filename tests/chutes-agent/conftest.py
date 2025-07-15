import os
import json


def pytest_configure(config):
    """Set up environment variables before any modules are imported."""
    os.environ["CLUSTER_NAME"] = "chutes-miner-gpu-0"
    os.environ["WATCH_NAMESPACES"] = '[]'
    
    # Print confirmation for debugging
    print("Environment variables set up for testing!")


pytest_configure(None)

from fixtures.client_fixtures import *  # noqa
from fixtures.agent_fixtures import *  # noqa
from fixtures.settings_fixtures import * # noqa
from fixtures.k8s_fixtures import * # noqa