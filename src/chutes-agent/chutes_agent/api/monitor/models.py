from typing import Annotated, Optional
from pydantic import BaseModel, Field, field_validator
from enum import Enum

class MonitoringState(str, Enum):
    """Monitoring status enumeration"""
    STOPPED = "stopped"
    STARTING = "starting"
    RUNNING = "running"
    ERROR = "error"

class StartMonitoringRequest(BaseModel):
    """Request to start monitoring a cluster"""
    control_plane_url: Annotated[str, Field(min_length=1)]
    
    @field_validator('control_plane_url')
    @classmethod
    def validate_url(cls, v):
        if not v or not v.strip():
            raise ValueError('URL cannot be empty')
        return v

class MonitoringStatus(BaseModel):
    """Current monitoring status"""
    cluster_id: Optional[str] = None
    state: str  # "stopped", "starting", "running", "error"
    error_message: Optional[str] = None
    last_heartbeat: Optional[str] = None
