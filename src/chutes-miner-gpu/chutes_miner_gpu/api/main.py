"""
Miner API entrypoint.
"""

import hashlib
from fastapi import FastAPI, Request
from fastapi.responses import ORJSONResponse
from chutes_miner_gpu.api.config.router import router as config_router


app = FastAPI(default_response_class=ORJSONResponse)
app.include_router(config_router, prefix="/config", tags=["Config"])
app.get("/ping")(lambda: {"message": "pong"})
