import json
import os

def pytest_configure(config):
    """Set up environment variables before any modules are imported."""
    os.environ["MINER_SS58"] = "5E6xfU3oNU7y1a7pQwoc31fmUjwBZ2gKcNCw8EXsdtCQieUQ"
    os.environ["MINER_SEED"] = "0xe031170f32b4cda05df2f3cf6bc8d7687b683bbce23d9fa960c0b3fc21641b8a"

    validators_json = {
        "supported": [
            {
                "hotkey": "test_validator",
                "registry": "test-registry",
                "api": "http://test-api",
                "socket": "ws://test-socket",
            }
        ]
    }
    os.environ["VALIDATORS"] = json.dumps(validators_json)

    # Print confirmation for debugging
    print("Environment variables set up for testing!")


pytest_configure(None)

from fixtures.monitor import *
from fixtures.k8s import *
from fixtures.router import *
from fixtures.requests import *
from fixtures.redis import *
from fixtures.health_checker import *
from fixtures.db import *