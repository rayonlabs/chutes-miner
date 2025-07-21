"""
Application-wide settings.
"""

import os
import json
from loguru import logger
import redis.asyncio as redis
from functools import lru_cache
from typing import Any
from kubernetes import client
from kubernetes.config import load_kube_config, load_incluster_config
from chutes_common.settings import MinerSettings as CommonSettings


def create_kubernetes_client(cls: Any = client.CoreV1Api):
    """
    Create a k8s client.
    """
    try:
        if os.getenv("KUBERNETES_SERVICE_HOST") is not None:
            load_incluster_config()
        else:
            load_kube_config(config_file=os.getenv("KUBECONFIG"))
        return cls()
    except Exception as exc:
        raise Exception(f"Failed to create Kubernetes client: {str(exc)}")


@lru_cache(maxsize=2)
def k8s_core_client() -> client.CoreV1Api:
    return create_kubernetes_client()


@lru_cache(maxsize=1)
def k8s_app_client() -> client.AppsV1Api:
    return create_kubernetes_client(cls=client.AppsV1Api)


@lru_cache(maxsize=1)
def k8s_api_client() -> client.ApiClient:
    return create_kubernetes_client(cls=client.ApiClient)


@lru_cache(maxsize=1)
def k8s_batch_client() -> client.BatchV1Api:
    return create_kubernetes_client(cls=client.BatchV1Api)


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
        "parachutes/graval-bootstrap-opencl:0.2.5-cuda",
    )
    graval_bootstrap_image_rocm: str = os.getenv(
        "GRAVAL_BOOTSTRAP_IMAGE",
        "parachutes/graval-bootstrap-opencl:0.2.5-rocm",
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

    monitor_api: str = str(os.getenv("MONITOR_API"))


settings = Settings()
