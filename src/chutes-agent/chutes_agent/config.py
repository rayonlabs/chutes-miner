# agent/config/config.py
import logging
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List, Optional, Dict
from loguru import logger

class AgentSettings(BaseSettings):
    """Agent configuration using pydantic-settings"""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )
    
    # Cluster identification
    cluster_name: str = Field(description="Human-readable cluster name")
    
    # Control plane connection
    # control_plane_url: str = Field(description="URL of the control plane API")
    control_plane_timeout: int = Field(default=30, description="Request timeout in seconds")
    control_plane_retry_attempts: int = Field(default=3, description="Number of retry attempts")
    
    # Heartbeat configuration
    heartbeat_interval: int = Field(default=30, description="Heartbeat interval in seconds")
    
    # Resource watching configuration
    watch_namespaces: List[str] = Field(
        default_factory=lambda: ["chutes"], 
        description="Namespaces to watch (empty = all)"
    )
    
    # Logging configuration
    log_level: str = Field(default="INFO", description="Logging level")
    log_format: str = Field(
        default="{time} | {level} | {name}:{function}:{line} | {message}",
        description="Log format string"
    )
    
    # Batch processing
    batch_size: int = Field(default=100, description="Batch size for processing resources")
    batch_timeout: int = Field(default=5, description="Batch timeout in seconds")
    
    control_plane_url_file: str = Field(default="/app/state/control_plane_url", descrption="File to store control plane URL for auto restarts.")

    def setup_logging(self) -> None:
        """Configure logging based on settings"""
        logger.remove()  # Remove default handler
        logger.add(
            sink=lambda message: print(message, end=''),
            level=self.log_level,
            format=self.log_format
        )
        
        # Intercept standard logging and redirect to loguru
        class InterceptHandler(logging.Handler):
            def emit(self, record):
                logger.opt(depth=6, exception=record.exc_info).log(record.levelname, record.getMessage())
        
        # Replace standard logging with intercept handler
        logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)
        
        # Specifically target uvicorn loggers
        for logger_name in ["uvicorn", "uvicorn.access", "uvicorn.error"]:
            uvicorn_logger = logging.getLogger(logger_name)
            uvicorn_logger.handlers = [InterceptHandler()]
            uvicorn_logger.propagate = False
        
        logger.info(f"Logging configured with level: {self.log_level}")


# Global settings instance
settings = AgentSettings()