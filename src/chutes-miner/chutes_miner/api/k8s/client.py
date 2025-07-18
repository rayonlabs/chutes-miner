import base64
from functools import lru_cache
from typing import Optional
from chutes_miner.api.k8s.config import KubeConfig, KubeContext, MultiClusterKubeConfig
from kubernetes import client, config


class KubernetesMultiClusterClientManager:
    def __init__(self):
        self.multi_config = MultiClusterKubeConfig()

    def get_api_client(self, context_name) -> client.ApiClient:
        return self._get_client_for_context(context_name)

    def get_app_client(self, context_name) -> client.AppsV1Api:
        api_client = self._get_client_for_context(context_name)
        return client.AppsV1Api(api_client)

    def get_core_client(
        self, context_name: str, kubeconfig: Optional[KubeConfig] = None
    ) -> client.CoreV1Api:
        api_client = self._get_client_for_context(context_name, kubeconfig)
        return client.CoreV1Api(api_client)

    @lru_cache(maxsize=10)
    def _get_client_for_context(self, context: str, kubeconfig: Optional[KubeConfig] = None) -> client.ApiClient:
        """Create a new client configured for the specified context"""

        _kubeconfig = kubeconfig if kubeconfig else self.multi_config.kubeconfig

        # Create configuration for this specific context
        return config.kube_config.new_client_from_config_dict(
            _kubeconfig.to_dict(),
            context=context,
            persist_config=False
        )
