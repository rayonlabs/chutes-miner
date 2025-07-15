# agent/controller/watcher.py
import asyncio
from typing import Any, Callable, Optional
from chutes_common.monitoring.models import ClusterState, MonitoringState, MonitoringStatus
from chutes_common.k8s import WatchEvent
from kubernetes_asyncio import client, config, watch
from chutes_agent.client import ControlPlaneClient
from chutes_agent.collector import ResourceCollector
from chutes_agent.config import settings
from loguru import logger
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
    after_log
)

class ResourceMonitor:
    def __init__(self):
        self.control_plane_client: Optional[ControlPlaneClient] = None
        self.collector = ResourceCollector()
        self.core_v1 = None
        self.apps_v1 = None
        self._status = MonitoringStatus(state=MonitoringState.STOPPED)
        self._watcher_task: Optional[asyncio.Task] = None
        
        # Restart protection
        self._restart_lock = asyncio.Lock()
        self._restart_task: Optional[asyncio.Task] = None

    @property
    def status(self):
        return self._status
        
    async def start(self, control_plane_url: str):
        self.control_plane_client = ControlPlaneClient(control_plane_url)
        await self._start_monitoring()

    async def stop(self):
        # Cancel any pending restart
        if self._restart_task and not self._restart_task.done():
            self._restart_task.cancel()
            try:
                await self._restart_task
            except asyncio.CancelledError:
                pass
        
        await self._stop_monitoring()
        await self.control_plane_client.remove_cluster()

    def _restart(self):
        """Initiate a restart with protection against spam restarts"""
        if self._restart_lock.locked():
            logger.info("Restart already in progress, skipping")
            return
        
        # Cancel any existing restart task
        if self._restart_task and not self._restart_task.done():
            self._restart_task.cancel()
        
        logger.info("Scheduling restart.")
        self._restart_task = asyncio.create_task(self._async_restart())

    @retry(
        stop=stop_after_attempt(10),
        wait=wait_exponential(
            multiplier=1,
            min=1,
            max=300,  # 5 minutes max
            exp_base=2
        ),
        retry=retry_if_exception_type((Exception,)),
        before_sleep=before_sleep_log(logger, logger.level("INFO").no),
        after=after_log(logger, logger.level("INFO").no)
    )
    async def _async_restart(self):
        """Async restart with retry logic"""
        async with self._restart_lock:
            logger.info("Executing restart")
            
            # Update status to restarting
            self._status.state = MonitoringState.STARTING
            self._status.error_message = "Restarting due to error"
            
            try:
                # Perform the restart
                await self.control_plane_client.remove_cluster()
                await self._stop_monitoring()
                await self._start_monitoring()
                
                logger.info("Restart completed successfully")
                
            except asyncio.CancelledError:
                logger.info("Restart was cancelled")
                self._status.state = MonitoringState.STOPPED
                # Don't retry on cancellation
                raise
            except Exception as e:
                logger.error(f"Restart attempt failed: {e}")
                # Set error state but let tenacity handle retries
                self._status.state = MonitoringState.ERROR
                self._status.error_message = f"Restart failed: {str(e)}"
                # Re-raise to trigger tenacity retry
                raise

    async def _start_monitoring(self):
        """Background task to start monitoring"""
        try:
            # Update status to running
            self._status.state = MonitoringState.STARTING
            self._status.error_message = None

            # Initialize and start watching
            await self.initialize()
            
            # Start the watching process
            self._watcher_task = asyncio.create_task(
                self._start_watch_resources()
            )
            
            # Update status to running
            self._status.state = MonitoringState.RUNNING
            self._status.error_message = None
            
            logger.info("Monitoring started successfully")

        except asyncio.CancelledError:
            logger.info("Monitoring task was cancelled")
            self._status.state = MonitoringState.STOPPED
        except Exception as e:
            logger.error(f"Monitoring task failed: {e}")
            self._status.state = MonitoringState.ERROR
            self._status.error_message = str(e)
            raise

    async def _stop_monitoring(self):
        """Stop the current monitoring task"""
        if self._watcher_task and not self._watcher_task.done():
            self._watcher_task.cancel()
            try:
                await self._watcher_task
            except asyncio.CancelledError:
                pass
        
        self._watcher_task = None
        self._status = MonitoringStatus(state=MonitoringState.STOPPED)
        logger.info("Monitoring stopped")

    async def initialize(self):
        """Initialize Kubernetes client and send initial resources"""
        try:
            config.load_incluster_config()
            
            # Initialize API clients
            self.core_v1 = client.CoreV1Api()
            self.apps_v1 = client.AppsV1Api()
            
            # Collect and send initial resources
            initial_resources = await self.collector.collect_all_resources()
            await self.control_plane_client.register_cluster(initial_resources)
            
            logger.info(f"Sent initial resources for cluster {settings.cluster_name}")
            
        except Exception as e:
            logger.error(f"Failed to initialize: {e}")
            raise
    
    async def _start_watch_resources(self):
        """Start watching all resource types"""
        try:
            tasks: list[asyncio.Task] = [
                asyncio.create_task(self.watch_nodes()),
                asyncio.create_task(self.send_heartbeat())
            ]
            for namespace in settings.watch_namespaces:
                namespace_tasks = [
                    asyncio.create_task(self.watch_namespaced_deployments(namespace)),
                    asyncio.create_task(self.watch_namespaced_pods(namespace)),
                    asyncio.create_task(self.watch_namespaced_services(namespace))
                ]
                tasks += namespace_tasks
            
            await asyncio.gather(*tasks, return_exceptions=True)
        except asyncio.CancelledError:
            for task in tasks:
                task.cancel()
            self._status.state = MonitoringState.STOPPED
        except Exception as err:
            self._status.state = MonitoringState.ERROR
            self._status.error_message = str(err)
            logger.error(f"Exception encoutering while watching resources: {err}")
    
    async def watch_namespaced_deployments(self, namespace: str):
        """Watch deployments for changes"""
        await self._watch_resources("deployments", self.apps_v1.list_namespaced_deployment, namespace=namespace)
    
    async def watch_namespaced_pods(self, namespace: str):
        """Watch pods for changes"""
        await self._watch_resources("pods", self.core_v1.list_namespaced_pod, namespace=namespace)
    
    async def watch_namespaced_services(self, namespace: str):
        """Watch services for changes"""
        await self._watch_resources("services", self.core_v1.list_namespaced_service, namespace=namespace)

    async def watch_nodes(self):
        """Watch services for changes"""
        await self._watch_resources("nodes", self.core_v1.list_node)

    async def _watch_resources(self, resource_type: str, func: Callable[..., Any], **kwargs) -> None:
        """Watch resources for changes"""
        while True:
            try:
                stream =  watch.Watch().stream(
                    func,
                    **kwargs
                )
                # Use the standard Kubernetes watch mechanism
                async for event in stream:
                    event = WatchEvent.from_dict(event)
                    await self.handle_resource_event(event)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error watching {resource_type}: {e}")
                self._restart()
                break
    
    async def handle_resource_event(self, event: WatchEvent):
        """Handle a resource change event"""
        try:
            await self.control_plane_client.send_resource_update(event)
            
            logger.debug(f"Sent {event.type} event for {event.obj_type}/{event.obj_name} in {event.obj_namespace}")
            
        except Exception as e:
            logger.error(f"Error handling {event.obj_type} event: {e}")
    
    async def send_heartbeat(self):
        """Send periodic heartbeat to control plane"""
        while True:
            try:
                await self.control_plane_client.send_heartbeat(ClusterState.ACTIVE)
                await asyncio.sleep(settings.heartbeat_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Failed to send heartbeat: {e}")
                # If a heartbeat failed just restart to ensure resources are synced properly.
                self._restart()
                break