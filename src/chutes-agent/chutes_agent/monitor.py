# agent/controller/watcher.py
import asyncio
import logging
import os
from typing import Any, Callable, Optional
from chutes_common.monitoring.models import ClusterState, MonitoringState, MonitoringStatus
from chutes_common.k8s import WatchEvent, serializer
from chutes_common.exceptions import ClusterConflictException, ClusterNotFoundException
from kubernetes_asyncio import client, config, watch
from kubernetes_asyncio.client.exceptions import ApiException
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
    after_log,
)

class ResourceMonitor:
    def __init__(self):
        self.control_plane_client: Optional[ControlPlaneClient] = None
        self.collector = ResourceCollector()
        self.core_v1 = None
        self.apps_v1 = None
        self.batch_v1 = None
        self._status = MonitoringStatus(state=MonitoringState.STOPPED)
        self._watcher_task: Optional[asyncio.Task] = None
        self._heartbeat_task: Optional[asyncio.Task] = None

        # Restart protection
        self._restart_lock = asyncio.Lock()
        self._restart_task: Optional[asyncio.Task] = None

        # Persistence - using mounted host path for persistence across pod restarts
        self._control_plane_url_file = settings.control_plane_url_file

        self.initialize()

    @property
    def status(self):
        return self._status

    @property
    def state(self) -> MonitoringState:
        return self._status.state
    
    @state.setter
    def state(self, value: MonitoringState):
        self._status.state = value

    def _ensure_state_directory(self):
        """Ensure the state directory exists"""
        state_dir = os.path.dirname(self._control_plane_url_file)
        try:
            os.makedirs(state_dir, exist_ok=True)
        except Exception as e:
            logger.warning(f"Failed to create state directory {state_dir}: {e}")

    def _persist_control_plane_url(self, url: str):
        """Persist control plane URL to file"""
        try:
            self._ensure_state_directory()
            with open(self._control_plane_url_file, "w") as f:
                f.write(url)
            logger.debug(f"Persisted control plane URL to {self._control_plane_url_file}")
        except Exception as e:
            logger.warning(f"Failed to persist control plane URL: {e}")

    def _load_control_plane_url(self) -> Optional[str]:
        """Load control plane URL from file"""
        try:
            if os.path.exists(self._control_plane_url_file):
                with open(self._control_plane_url_file, "r") as f:
                    url = f.read().strip()
                logger.debug(f"Loaded control plane URL from {self._control_plane_url_file}")
                return url
        except Exception as e:
            logger.warning(f"Failed to load control plane URL: {e}")
        return None

    def _clear_control_plane_url(self):
        """Clear persisted control plane URL"""
        try:
            if os.path.exists(self._control_plane_url_file):
                os.remove(self._control_plane_url_file)
                logger.debug("Cleared persisted control plane URL")
        except Exception as e:
            logger.warning(f"Failed to clear control plane URL: {e}")

    async def auto_start(self):
        """Auto-start monitoring if control plane URL is persisted"""
        url = self._load_control_plane_url()
        if url:
            logger.info("Found persisted control plane URL, auto-starting monitoring")
            try:
                self.control_plane_client = ControlPlaneClient(url)
                await self._send_all_resources()
                await self._start_monitoring_tasks()
            except Exception as e:
                logger.error(f"Failed to auto-start monitoring:\n{str(e)}")
        else:
            logger.info(
                "Did not find control plane URL.  Waiting for monitoring to be initiated by control plane."
            )

    async def start(self, control_plane_url: str):
        # Persist the control plane URL
        try:
            self._persist_control_plane_url(control_plane_url)

            self.control_plane_client = ControlPlaneClient(control_plane_url)
            await self._register_cluster()
            await self._start_monitoring_tasks()
        except Exception as e:
            error_message = f"Unexpected error encountered while starting:\n{str(e)}"
            logger.error(error_message)
            self.state = MonitoringState.ERROR
            self.status.error_message = error_message
            raise

    async def stop(self):
        await self.stop_monitoring_tasks()

        # Clear persisted URL when explicitly stopped
        # Clean up client
        if self.control_plane_client:
            await self.control_plane_client.remove_cluster()
            await self.control_plane_client.close()

        self._clear_control_plane_url()

        await serializer.close()

    async def stop_monitoring_tasks(self):
        # Cancel any pending restart
        if self._restart_task and not self._restart_task.done():
            self._restart_task.cancel()
            try:
                await self._restart_task
            except asyncio.CancelledError:
                pass

        await self._stop_monitoring_tasks()

    def _restart(self):
        """Initiate a restart with protection against spam restarts"""
        if self._restart_lock.locked():
            logger.info("Restart already in progress, skipping")
            return

        # Cancel any existing restart task
        if self._restart_task and not self._restart_task.done():
            self._restart_task.cancel()

        # Only restart if we are still in a running state
        if self.state == MonitoringState.RUNNING:
            logger.info("Scheduling restart.")
            self._restart_task = asyncio.create_task(self._async_restart())
        else:
            logger.info(f"Skipping restart, monitoring state {self.state=}")

    @retry(
        stop=stop_after_attempt(10),
        wait=wait_exponential(
            multiplier=1,
            min=1,
            max=300,  # 5 minutes max
            exp_base=2,
        ),
        retry=retry_if_exception_type((Exception,)),
        before_sleep=before_sleep_log(logger, logger.level("INFO").no),
        after=after_log(logger, logger.level("INFO").no),
    )
    async def _async_restart(self):
        """Async restart with retry logic"""
        async with self._restart_lock:
            logger.info("Executing restart")

            # Update status to restarting
            self.state = MonitoringState.STARTING
            self.status.error_message = "Restarting due to error"

            try:
                # Perform the restart
                await self._stop_monitoring_tasks()
                await self._send_all_resources()
                await self._start_monitoring_tasks()

                logger.info("Restart completed successfully")

            except asyncio.CancelledError:
                logger.info("Restart was cancelled")
                self.state = MonitoringState.STOPPED
                # Don't retry on cancellation
                raise
            except Exception as e:
                logger.error(f"Restart attempt failed: {e}")
                # Set error state but let tenacity handle retries
                self.state = MonitoringState.ERROR
                self.status.error_message = f"Restart failed: {str(e)}"
                # Re-raise to trigger tenacity retry
                raise

    async def _start_monitoring_tasks(self):
        """Background task to start monitoring"""
        try:
            # Update status to running
            self.state = MonitoringState.STARTING
            self.status.error_message = None

            # Initialize and start watching
            self._heartbeat_task = asyncio.create_task(self.send_heartbeat())

            # Start the watching process
            self._watcher_task = asyncio.create_task(self._start_watch_resources())

            # Update status to running
            self.state = MonitoringState.RUNNING
            self.status.error_message = None

            logger.info("Monitoring started successfully")

        except asyncio.CancelledError:
            logger.info("Monitoring task was cancelled")
            self.state = MonitoringState.STOPPED
        except Exception as e:
            logger.error(f"Monitoring task failed: {e}")
            self.state = MonitoringState.ERROR
            self.status.error_message = str(e)
            raise

    async def _stop_monitoring_tasks(self):
        """Stop the current monitoring task"""
        if self._watcher_task and not self._watcher_task.done():
            self._watcher_task.cancel()
            try:
                await self._watcher_task
            except asyncio.CancelledError:
                pass

        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass

        self._watcher_task = None
        self._heartbeat_task = None
        self._status = MonitoringStatus(state=MonitoringState.STOPPED)
        logger.info("Monitoring stopped")

    def initialize(self):
        """Initialize Kubernetes client and send initial resources"""
        try:
            config.load_incluster_config()

            # Initialize API clients
            self.core_v1 = client.CoreV1Api()
            self.apps_v1 = client.AppsV1Api()
            self.batch_v1 = client.BatchV1Api()

        except Exception as e:
            logger.error(f"Failed to initialize: {e}")
            raise

    async def _register_cluster(self):
        # Collect and send initial resources
        initial_resources = await self.collector.collect_all_resources()
        try:
            await self.control_plane_client.register_cluster(initial_resources)
        except ClusterConflictException:
            await self.control_plane_client.remove_cluster()
            await self.control_plane_client.register_cluster(initial_resources)

        logger.info(f"Registered cluster with control plane.")

    async def _send_all_resources(self):
        # Collect and send initial resources
        initial_resources = await self.collector.collect_all_resources()
        try:
            await self.control_plane_client.set_cluster_resources(initial_resources)
        except ClusterNotFoundException:
            await self.control_plane_client.register_cluster(initial_resources)

        logger.info(f"Sent resources for cluster {settings.cluster_name}")

    async def _start_watch_resources(self):
        """Start watching all resource types"""
        try:
            tasks: list[asyncio.Task] = [asyncio.create_task(self.watch_nodes())]
            for namespace in settings.watch_namespaces:
                namespace_tasks = [
                    asyncio.create_task(self.watch_namespaced_deployments(namespace)),
                    asyncio.create_task(self.watch_namespaced_pods(namespace)),
                    asyncio.create_task(self.watch_namespaced_services(namespace)),
                    asyncio.create_task(self.watch_namespaced_jobs(namespace)),
                ]
                tasks += namespace_tasks

            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            for task in tasks:
                task.cancel()
            self.state = MonitoringState.STOPPED
        except Exception as err:
            self.state = MonitoringState.ERROR
            self.status.error_message = str(err)
            logger.error(f"Exception encoutering while watching resources: {err}")
            self._restart()
            

    async def watch_namespaced_deployments(self, namespace: str):
        """Watch deployments for changes"""
        await self._watch_resources(
            "deployments", self.apps_v1.list_namespaced_deployment, namespace=namespace
        )

    async def watch_namespaced_pods(self, namespace: str):
        """Watch pods for changes"""
        await self._watch_resources("pods", self.core_v1.list_namespaced_pod, namespace=namespace)

    async def watch_namespaced_services(self, namespace: str):
        """Watch services for changes"""
        await self._watch_resources(
            "services", self.core_v1.list_namespaced_service, namespace=namespace
        )

    async def watch_namespaced_jobs(self, namespace: str):
        """Watch jobs for changes"""
        await self._watch_resources(
            "jobs", self.batch_v1.list_namespaced_job, namespace=namespace
        )

    async def watch_nodes(self):
        """Watch services for changes"""
        await self._watch_resources("nodes", self.core_v1.list_node)

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=1, max=60),
        retry=retry_if_exception_type(Exception),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        after=after_log(logger, logging.DEBUG),
        reraise=True
    )
    async def _get_initial_resource_version(self, func, **kwargs):
        """Get initial resource version with retry logic"""
        initial_list = await func(**kwargs, watch=False)
        resource_version = initial_list.metadata.resource_version
        logger.debug(f"Got initial resource version: {resource_version}")
        return resource_version

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=2, min=1, max=30),
        retry=retry_if_exception_type(Exception),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True
    )
    async def _process_watch_stream(self, func, resource_version, **kwargs):
        """Process a single watch stream with retry for transient errors"""
        watch_kwargs = kwargs.copy()
        watch_kwargs.update({
            'watch': True,
            'resource_version': resource_version,
            'timeout_seconds': 300,  # 5 minute timeout
            'limit': 200,
        })
        
        logger.debug(f"Starting watch stream from resource version {resource_version}")
        
        async with watch.Watch().stream(func, **watch_kwargs) as stream:
            event_count = 0
            stream_start_time = asyncio.get_event_loop().time()
            
            async for event in stream:
                try:
                    event_count += 1
                    event = WatchEvent.from_dict(event)
                    
                    # Update resource version from each event
                    if (hasattr(event.object, 'metadata') and 
                        hasattr(event.object.metadata, 'resource_version')):
                        resource_version = event.object.metadata.resource_version
                    
                    await self.handle_resource_event(event)
                    
                    # Log progress periodically
                    if event_count % 10 == 0:
                        elapsed = asyncio.get_event_loop().time() - stream_start_time
                        logger.debug(f"Processed {event_count} events in {elapsed:.1f}s")
                        
                except Exception as e:
                    logger.error(f"Error processing event: {e}")
                    # Continue processing other events
                    continue
            
            # Stream ended normally
            elapsed = asyncio.get_event_loop().time() - stream_start_time
            logger.debug(f"Watch stream ended after {elapsed:.1f}s, {event_count} events")
            
        return resource_version  # Return updated resource version

    async def _watch_resources(
        self, resource_type: str, func: Callable[..., Any], **kwargs
    ) -> None:
        """Watch resources for changes with tenacity-managed retries"""
        resource_version = None
        
        while True:
            try:
                logger.debug(f"Watching {resource_type}")
                
                # Get initial resource version if needed
                if resource_version is None:
                    try:
                        resource_version = await self._get_initial_resource_version(func, **kwargs)
                    except Exception as e:
                        logger.error(f"Failed to get initial {resource_type} list after retries: {e}")
                        await asyncio.sleep(5)
                        continue
                
                # Process watch stream
                try:
                    resource_version = await self._process_watch_stream(
                        func, resource_version, **kwargs
                    )
                except ApiException as e:
                    if e.status == 410:  # Gone - resource version too old
                        logger.warning(f"{resource_type} resource version {resource_version} too old, resetting")
                        resource_version = None
                        await asyncio.sleep(1)
                        continue
                    else:
                        # Let tenacity handle other API exceptions
                        raise
                except asyncio.TimeoutError:
                    # Normal timeout, just restart
                    logger.debug(f"{resource_type} watch timed out, restarting (normal)")
                    continue
                    
            except asyncio.CancelledError:
                logger.info(f"{resource_type} watch cancelled")
                break
                
            except Exception as e:
                logger.error(f"Unhandled error watching {resource_type}: {e}")
                # If we get here, tenacity has exhausted retries
                logger.error(f"Exhausted retries for {resource_type}, triggering restart")
                self._restart()
                break

    async def handle_resource_event(self, event: WatchEvent):
        """Handle a resource change event"""
        try:
            await self.control_plane_client.send_resource_update(event)

            logger.debug(
                f"Sent {event.type} event for {event.obj_type}/{event.obj_name} in {event.obj_namespace}"
            )

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
