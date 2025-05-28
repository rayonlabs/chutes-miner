import json
from typing import Dict, Any


class ApiResponse:
    def __init__(self, dict: Dict[str, Any]):
        self.data = json.dumps(dict)
