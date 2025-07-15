# agent/controller/collector.py
from chutes_common.monitoring.models import ClusterResources
from kubernetes_asyncio import client, config
from loguru import logger
from typing import Dict, List, Any
from chutes_agent.config import settings

class ResourceCollector:
    """Collects initial resource snapshots from Kubernetes cluster"""
    
    def __init__(self):
        self.core_v1 = None
        self.apps_v1 = None
        self.namespaces = settings.watch_namespaces
    
    def initialize_clients(self):
        """Initialize Kubernetes API clients"""
        config.load_incluster_config()
        self.core_v1 = client.CoreV1Api()
        self.apps_v1 = client.AppsV1Api()
    
    async def collect_all_resources(self) -> ClusterResources:
        """Collect all monitored resources from the cluster"""
        if not self.core_v1:
            self.initialize_clients()
        
        resources = ClusterResources()
        try:
            nodes_response = await self.core_v1.list_node()
            resources.nodes.extend(nodes_response.items)

            # Collect from specific namespaces
            for namespace in self.namespaces:
                try:
                    # Collect deployments for this namespace
                    deployments_response = await self.apps_v1.list_namespaced_deployment(namespace)
                    resources.deployments.extend(deployments_response.items)
                    
                    # Collect pods for this namespace
                    pods_response = await self.core_v1.list_namespaced_pod(namespace)
                    resources.pods.extend(pods_response.items)
                    
                    # Collect services for this namespace
                    services_response = await self.core_v1.list_namespaced_service(namespace)
                    resources.services.extend(services_response.items)

                    logger.debug(f"Collected from namespace {namespace}: {len(deployments_response.items)} deployments, {len(pods_response.items)} pods, {len(services_response.items)} services, {len(nodes_response.items)} nodes")
                    
                except Exception as e:
                    logger.warning(f"Error collecting resources from namespace {namespace}: {e}")
                    continue
            
            logger.info(f"Collected from {len(self.namespaces)} namespaces: {len(resources.deployments)} deployments, {len(resources.pods)} pods, {len(resources.services)} services")
        
        
        except Exception as e:
            logger.error(f"Error collecting resources: {e}")
            raise
        
        return resources