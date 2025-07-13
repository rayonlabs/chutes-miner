import os
from pydantic import Field
from pydantic_settings import BaseSettings


class MonitorSettings(BaseSettings):

    heartbeat_interval: int = Field(default=30, description="")
    failure_threshold: int = Field(default=1, description="", alias="HEALTH_FAILURE_THRESHOLD")
    redis_url: str = Field(default ='redis://redis:6379', description="")
    # control_plane_url: str = Field(default="localhost:8000", description="URL to provide to agents")

settings = MonitorSettings()