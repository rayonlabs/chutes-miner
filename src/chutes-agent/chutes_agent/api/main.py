"""
Miner Agent API entrypoint.
"""

from contextlib import asynccontextmanager
import hashlib
from fastapi import FastAPI, Request
from fastapi.responses import ORJSONResponse
from chutes_agent.api.config.router import router as config_router
from chutes_agent.api.monitor.router import router as monitor_router
from chutes_agent.api.monitor.router import resource_monitor
from chutes_agent.config import settings
from loguru import logger
from chutes_common.k8s import serializer

settings.setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifespan events"""
    # Startup
    logger.info("Starting Control Plane API server")
    print("Starting Control Plane API server")

    # Import here to avoid circular imports
    # from chutes_agent.api.monitor.router import resource_monitor

    # Try to auto-start monitoring if configuration exists
    await resource_monitor.auto_start()

    logger.info("Agent API server started successfully")

    yield

    # Shutdown
    logger.info("Shutting down Agent API server")

    # Stop monitoring on shutdown
    await resource_monitor.stop_monitoring_tasks()

    # Close serializer API connection
    await serializer.close()

    logger.info("Agent API server stopped")


app = FastAPI(lifespan=lifespan, default_response_class=ORJSONResponse)
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
