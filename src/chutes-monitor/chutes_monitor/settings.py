from chutes_common.settings import RedisSettings
from pydantic import Field


class MonitorSettings(RedisSettings):
    heartbeat_interval: int = Field(default=30, description="")
    failure_threshold: int = Field(default=1, description="", alias="HEALTH_FAILURE_THRESHOLD")

    sqlalchemy: str = Field(
        default="postgresql+asyncpg://user:password@127.0.0.1:5432/chutes", 
        description="",
        alias="POSTGRESQL"
    )

    debug: bool = Field(default=False, description="")


settings = MonitorSettings()
