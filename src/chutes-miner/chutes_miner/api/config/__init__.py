"""
Application-wide settings.
"""

import os
import json
from loguru import logger
import redis.asyncio as redis
from functools import lru_cache
from typing import Any, Optional
from kubernetes import client
from kubernetes.config import load_kube_config, load_incluster_config
from chutes_common.settings import MinerSettings as CommonSettings


def create_kubernetes_client(cls: Any = client.CoreV1Api, karmada_api: bool = False):
    """
    Create a k8s client.
    """
    try:
        if karmada_api:
            kubeconfig_path = os.path.expanduser(os.getenv("KUBECONFIG", "/etc/karmada/kubeconfig"))

            if not os.path.exists(kubeconfig_path):
                raise RuntimeError(f"Karmada kubeconfig not found at {kubeconfig_path}")

            logger.debug(f"Loading in Karmada API server config [{cls=}]")
            load_kube_config(config_file=kubeconfig_path, context="karmada-apiserver")
        elif os.getenv("KUBERNETES_SERVICE_HOST") is not None:
            logger.debug(f"Loading in cluster config [{cls=}]")
            load_incluster_config()
        else:
            raise RuntimeError(
                "Unable to determine kubernetes configuration from environment. Set either 'KUBECONFIG' or 'KUBERNETES_SERVICE_HOST' environment variable."
            )
        return cls()
    except Exception as exc:
        raise Exception(f"Failed to create Kubernetes client: {str(exc)}")


@lru_cache(maxsize=2)
def k8s_core_client(karmada_api: bool = False) -> client.CoreV1Api:
    return create_kubernetes_client(karmada_api=karmada_api)


@lru_cache(maxsize=1)
def k8s_app_client(karmada_api: bool = False) -> client.AppsV1Api:
    return create_kubernetes_client(cls=client.AppsV1Api, karmada_api=karmada_api)


@lru_cache(maxsize=1)
def k8s_api_client(karmada_api: bool = False) -> client.ApiClient:
    return create_kubernetes_client(cls=client.ApiClient, karmada_api=karmada_api)


@lru_cache(maxsize=1)
def k8s_custom_objects_client(karmada_api: bool = False) -> client.CustomObjectsApi:
    return create_kubernetes_client(cls=client.CustomObjectsApi, karmada_api=karmada_api)


@lru_cache(maxsize=32)
def validator_by_hotkey(hotkey: str):
    valis = [validator for validator in settings.validators if validator.hotkey == hotkey]
    if valis:
        return valis[0]
    return None


class Settings(CommonSettings):

    sqlalchemy: str = os.getenv(
        "POSTGRESQL", "postgresql+asyncpg://user:password@127.0.0.1:5432/chutes"
    )
    redis_url: str = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
    redis_client: redis.Redis = redis.Redis.from_url(
        os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
    )
    netuid: int = int(os.getenv("NETUID", "64"))
    subtensor: str = os.getenv("SUBTENSOR_ADDRESS", "wss://entrypoint-finney.opentensor.ai:443")
    namespace: str = os.getenv("CHUTES_NAMESPACE", "chutes")
    graval_bootstrap_image: str = os.getenv(
        "GRAVAL_BOOTSTRAP_IMAGE",
        "parachutes/graval-bootstrap:0.1.2-opencl",
    )
    nvidia_runtime: str = os.getenv("NVIDIA_RUNTIME", "nvidia")
    graval_bootstrap_timeout: int = int(os.getenv("GRAVAL_BOOTSTRAP_TIMEOUT", "900"))
    debug: bool = os.getenv("DEBUG", "false").lower() == "true"
    registry_proxy_port: int = int(os.getenv("REGISTRY_PROXY_PORT", "30500"))
    monitoring_namespace: str = os.getenv("MONITORING_NAMESPACE", "chutes")
    prometheus_url: str = f"http://prometheus-server.{os.getenv('MONITORING_NAMESPACE', 'chutes')}.svc.cluster.local:{os.getenv('PROMETHEUS_PORT', '80')}"

    cache_max_age_days: int = int(os.getenv("CACHE_MAX_AGE_DAYS", "7"))
    cache_max_size_gb: int = int(os.getenv("CACHE_MAX_SIZE_GB", "500"))
    cache_overrides: dict = json.loads(os.getenv("CACHE_OVERRIDES", "{}")) or {}

    migrations_dir: str = os.getenv("MIGRATIONS_DIR", "chutes-miner/chutes_miner/api/migrations")

    gpu_node_api_port: int = int(os.getenv("GPU_NODE_API_PORT", "32001"))

settings = Settings()
