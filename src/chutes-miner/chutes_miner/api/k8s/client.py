import base64
from functools import lru_cache
from typing import Optional
from chutes_miner.api.k8s.config import KubeConfig, KubeContext, MultiClusterKubeConfig
from kubernetes import client


class KubernetesMultiClusterClientManager:
    def __init__(self):
        self.multi_config = MultiClusterKubeConfig()

    def get_api_client(self, context_name) -> client.ApiClient:
        context = self.multi_config.get_context(context_name)
        return self._get_client_for_context(context)

    def get_app_client(self, context_name) -> client.AppsV1Api:
        context = self.multi_config.get_context(context_name)
        api_client = self._get_client_for_context(context)
        return client.AppsV1Api(api_client)

    def get_core_client(
        self, context_name: str, kubeconfig: Optional[KubeConfig] = None
    ) -> client.CoreV1Api:
        if kubeconfig:
            context = next([ctx for ctx in kubeconfig.contexts if ctx.name == context_name], None)
            if not context:
                raise ValueError(
                    f"Can not create client using provided kubeconfig, context {context_name} does not exist."
                )
            api_client = self._get_client_for_context(context)
        else:
            context = self.multi_config.get_context(context_name)
            api_client = self._get_client_for_context(context)
        return client.CoreV1Api(api_client)

    @lru_cache(maxsize=10)
    def _get_client_for_context(self, context: KubeContext) -> client.ApiClient:
        """Create a new client configured for the specified context"""

        # Create configuration for this specific context
        configuration = client.Configuration()
        configuration.host = context.cluster.server

        # Handle SSL verification
        if context.cluster.certificate_authority_data:
            ca_cert_data = base64.b64decode(context.cluster.certificate_authority_data).decode(
                "utf-8"
            )
            configuration.ssl_ca_cert = ca_cert_data
        else:
            configuration.verify_ssl = not context.cluster.insecure_skip_tls_verify

        # Handle authentication
        if context.user.token:
            configuration.api_key = {"authorization": "Bearer " + context.user.token}
            configuration.api_key_prefix = {"authorization": "Bearer"}
        elif context.user.client_certificate_data and context.user.client_key_data:
            cert_data = base64.b64decode(context.user.client_certificate_data).decode("utf-8")
            key_data = base64.b64decode(context.user.client_key_data).decode("utf-8")

            configuration.cert_file = cert_data
            configuration.key_file = key_data

        # Return new client instance
        return client.ApiClient(configuration)

    # def execute_on_context(self, context_name: str, operation):
    #     """Execute an operation on a specific context"""
    #     k8s_client = self.get_client_for_context(context_name)
    #     v1 = client.CoreV1Api(k8s_client)
    #     return operation(v1)

    # def execute_on_all_contexts(self, operation):
    #     """Execute an operation on all contexts"""
    #     results = {}

    #     for context_name in self.multi_config.contexts:
    #         try:
    #             result = self.execute_on_context(context_name, operation)
    #             results[context_name] = result
    #         except Exception as e:
    #             results[context_name] = f"Error: {str(e)}"

    #     return results
