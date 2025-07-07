import os
import json


def pytest_configure(config):
    """Set up environment variables before any modules are imported."""
    # os.environ["MINER_SS58"] = "5E6xfU3oNU7y1a7pQwoc31fmUjwBZ2gKcNCw8EXsdtCQieUQ"
    # os.environ["MINER_SEED"] = "0xe031170f32b4cda05df2f3cf6bc8d7687b683bbce23d9fa960c0b3fc21641b8a"

    # validators_json = {
    #     "supported": [
    #         {
    #             "hotkey": "test_validator",
    #             "registry": "test-registry",
    #             "api": "http://test-api",
    #             "socket": "ws://test-socket",
    #         }
    #     ]
    # }
    # os.environ["VALIDATORS"] = json.dumps(validators_json)

    # # Print confirmation for debugging
    # print("Environment variables set up for testing!")


pytest_configure(None)


from fixtures.api_fixtures import *  # noqa
from fixtures.cli_fixtures import *  # noqa