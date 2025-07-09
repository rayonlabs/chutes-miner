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

@app.middleware("http")
async def request_body_checksum(request: Request, call_next):
    if request.method in ["POST", "PUT", "PATCH"]:
        body = await request.body()
        sha256_hash = hashlib.sha256(body).hexdigest()
        request.state.body_sha256 = sha256_hash
    else:
        request.state.body_sha256 = None
    return await call_next(request)