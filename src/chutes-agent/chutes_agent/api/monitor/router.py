# agent/api/monitor/router.py
from chutes_common.monitoring.models import MonitoringState, MonitoringStatus
from chutes_common.monitoring.requests import StartMonitoringRequest
from fastapi import APIRouter, HTTPException
from loguru import logger

from chutes_agent.monitor import ResourceMonitor
from chutes_agent.config import settings

# Router instance
router = APIRouter()

# Global monitoring state
resource_monitor = ResourceMonitor()

@router.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "cluster": settings.cluster_name}

@router.get("/status")
async def get_status() -> MonitoringStatus:
    """Get current monitoring status"""
    return resource_monitor.status

@router.post("/start")
async def start_monitoring(
    request: StartMonitoringRequest
):
    """Start monitoring with provided configuration"""
    try:
        # Stop existing monitoring if running
        if resource_monitor.status == MonitoringState.RUNNING:
            logger.info("Stopping existing monitoring task")
            await resource_monitor.stop()
            # await stop_monitoring_task()
        
        await resource_monitor.start(request.control_plane_url)

        return {"message": "Monitoring started", "cluster": settings.cluster_name}
        
    except Exception as e:
        logger.error(f"Failed to start monitoring: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/stop")
async def stop_monitoring():
    """Stop monitoring"""
    try:
        await resource_monitor.stop()
        return {"message": "Monitoring stopped"}
    except Exception as e:
        logger.error(f"Failed to stop monitoring: {e}")
        raise HTTPException(status_code=500, detail=str(e))