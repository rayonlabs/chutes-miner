"""
Utility/helper functions.
"""

import datetime
import orjson as json


def now_str():
    """
    Return current (UTC) timestamp as string.
    """
    return datetime.datetime.utcnow().isoformat()


def sse(data):
    """
    Format response object for server-side events stream.
    """
    return f"data: {json.dumps(data).decode()}\n\n"


def sse_message(message):
    """
    Format a simple trace message with timestamp.
    """
    return sse(
        {
            "timestamp": now_str(),
            "message": message,
        }
    )
