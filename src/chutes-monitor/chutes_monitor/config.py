from chutes_common.settings import RedisSettings
from pydantic import Field


class MonitorSettings(RedisSettings):
    heartbeat_interval: int = Field(default=30, description="")
    failure_threshold: int = Field(default=1, description="", alias="HEALTH_FAILURE_THRESHOLD")
    # control_plane_url: str = Field(default="localhost:8000", description="URL to provide to agents")


settings = MonitorSettings()
