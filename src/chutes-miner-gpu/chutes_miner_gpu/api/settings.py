import os
from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    miner_kube_config: Path = Field(
        default=Path(f"{os.path.expanduser('~')}/.kube/miner.config"),
        description="Path to the Miner Kubernetes configuration file",
    )

    class Config:
        env_prefix = ""  # No prefix needed since we're using the full env var name
        env_file = ".env"  # Optional: also load from .env file
        case_sensitive = False
