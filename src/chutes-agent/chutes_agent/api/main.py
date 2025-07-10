"""
Miner Agent API entrypoint.
"""

import hashlib
from fastapi import FastAPI, Request
from fastapi.responses import ORJSONResponse
from chutes_agent.api.config.router import router as config_router
from chutes_agent.api.monitor.router import router as monitor_router
from chutes_agent.config import settings

settings.setup_logging()

app = FastAPI(default_response_class=ORJSONResponse)
app.include_router(config_router, prefix="/config", tags=["Config"])
app.include_router(monitor_router, prefix="/monitor", tags=["Monitor"])
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