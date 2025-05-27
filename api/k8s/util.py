import uuid
from kubernetes.client import (
    V1Deployment,
    V1Service,
    V1ObjectMeta,
    V1DeploymentSpec,
    V1DeploymentStrategy,
    V1PodTemplateSpec,
    V1PodSpec,
    V1Container,
    V1ResourceRequirements,
    V1ServiceSpec,
    V1ServicePort,
    V1Probe,
    V1EnvVar,
    V1Volume,
    V1VolumeMount,
    V1ConfigMapVolumeSource,
    V1HostPathVolumeSource,
    V1SecurityContext,
    V1EmptyDirVolumeSource,
    V1ExecAction,
)

from api.chute.schemas import Chute
from api.server.schemas import Server
from api.config import settings


def build_chute_deployment(deployment_id, chute: Chute, server: Server) -> V1Deployment:
    cpu = str(server.cpu_per_gpu * chute.gpu_count)
    ram = str(server.memory_per_gpu * chute.gpu_count) + "Gi"
    code_uuid = str(uuid.uuid5(uuid.NAMESPACE_OID, f"{chute.chute_id}::{chute.version}"))
    deployment_labels = {
        "chutes/deployment-id": deployment_id,
        "chutes/chute": "true",
        "chutes/chute-id": chute.chute_id,
        "chutes/version": chute.version,
        "squid-access": "true",
    }
    return V1Deployment(
        metadata=V1ObjectMeta(
            name=f"chute-{deployment_id}",
            labels=deployment_labels,
        ),
        spec=V1DeploymentSpec(
            replicas=1,
            strategy=V1DeploymentStrategy(type="Recreate"),
            selector={"matchLabels": {"chutes/deployment-id": deployment_id}},
            template=V1PodTemplateSpec(
                metadata=V1ObjectMeta(
                    labels=deployment_labels,
                    annotations={
                        "prometheus.io/scrape": "true",
                        "prometheus.io/path": "/_metrics",
                        "prometheus.io/port": "8000",
                    },
                ),
                spec=V1PodSpec(
                    node_name=server.name,
                    runtime_class_name=settings.nvidia_runtime,
                    volumes=[
                        V1Volume(
                            name="code",
                            config_map=V1ConfigMapVolumeSource(
                                name=f"chute-code-{code_uuid}",
                            ),
                        ),
                        V1Volume(
                            name="cache",
                            host_path=V1HostPathVolumeSource(
                                path="/var/snap/cache", type="DirectoryOrCreate"
                            ),
                        ),
                        V1Volume(
                            name="cache-cleanup",
                            config_map=V1ConfigMapVolumeSource(
                                name="chutes-cache-cleaner",
                            ),
                        ),
                        V1Volume(
                            name="tmp",
                            empty_dir=V1EmptyDirVolumeSource(size_limit="10Gi"),
                        ),
                        V1Volume(
                            name="shm",
                            empty_dir=V1EmptyDirVolumeSource(medium="Memory", size_limit="16Gi"),
                        ),
                    ],
                    init_containers=[
                        V1Container(
                            name="cache-init",
                            image="parachutes/cache-cleaner:latest",
                            command=["/bin/bash", "-c"],
                            args=[
                                "mkdir -p /cache/hub /cache/civitai && chmod -R 777 /cache && python /scripts/cache_cleanup.py"
                            ],
                            env=[
                                V1EnvVar(
                                    name="HF_HOME",
                                    value="/cache",
                                ),
                                V1EnvVar(
                                    name="CIVITAI_HOME",
                                    value="/cache/civitai",
                                ),
                                V1EnvVar(
                                    name="CACHE_MAX_AGE_DAYS",
                                    value=str(settings.cache_max_age_days),
                                ),
                                V1EnvVar(
                                    name="CACHE_MAX_SIZE_GB",
                                    value=str(
                                        settings.cache_overrides.get(
                                            server.name, settings.cache_max_size_gb
                                        )
                                    ),
                                ),
                            ],
                            volume_mounts=[
                                V1VolumeMount(name="cache", mount_path="/cache"),
                                V1VolumeMount(
                                    name="cache-cleanup",
                                    mount_path="/scripts",
                                ),
                            ],
                            security_context=V1SecurityContext(
                                run_as_user=0,
                                run_as_group=0,
                            ),
                        ),
                    ],
                    containers=[
                        V1Container(
                            name="chute",
                            image=f"{server.validator.lower()}.localregistry.chutes.ai:{settings.registry_proxy_port}/{chute.image}",
                            image_pull_policy="Always",
                            env=[
                                V1EnvVar(
                                    name="CHUTES_EXECUTION_CONTEXT",
                                    value="REMOTE",
                                ),
                                V1EnvVar(
                                    name="VLLM_DISABLE_TELEMETRY",
                                    value="1",
                                ),
                                V1EnvVar(
                                    name="NCCL_DEBUG",
                                    value="INFO",
                                ),
                                V1EnvVar(
                                    name="HTTP_PROXY",
                                    value=settings.squid_url or "",
                                ),
                                V1EnvVar(
                                    name="HTTPS_PROXY",
                                    value=settings.squid_url or "",
                                ),
                                V1EnvVar(
                                    name="NCCL_SOCKET_IFNAME",
                                    value="^docker,lo",
                                ),
                                V1EnvVar(
                                    name="NCCL_P2P_DISABLE",
                                    value="1",
                                ),
                                V1EnvVar(
                                    name="NCCL_IB_DISABLE",
                                    value="1",
                                ),
                                V1EnvVar(
                                    name="NCCL_SHM_DISABLE",
                                    value="0",
                                ),
                                V1EnvVar(
                                    name="NCCL_NET_GDR_LEVEL",
                                    value="0",
                                ),
                                V1EnvVar(
                                    name="CUDA_VISIBLE_DEVICES",
                                    value=",".join([str(idx) for idx in range(chute.gpu_count)]),
                                ),
                                V1EnvVar(name="HF_HOME", value="/cache"),
                                V1EnvVar(name="CIVITAI_HOME", value="/cache/civitai"),
                            ],
                            resources=V1ResourceRequirements(
                                requests={
                                    "cpu": cpu,
                                    "memory": ram,
                                    "nvidia.com/gpu": str(chute.gpu_count),
                                },
                                limits={
                                    "cpu": cpu,
                                    "memory": ram,
                                    "nvidia.com/gpu": str(chute.gpu_count),
                                },
                            ),
                            volume_mounts=[
                                V1VolumeMount(
                                    name="code",
                                    mount_path=f"/app/{chute.filename}",
                                    sub_path=chute.filename,
                                ),
                                V1VolumeMount(name="cache", mount_path="/cache"),
                                V1VolumeMount(name="tmp", mount_path="/tmp"),
                                V1VolumeMount(name="shm", mount_path="/dev/shm"),
                            ],
                            security_context=V1SecurityContext(
                                # XXX Would love to add this, but vllm (and likely other libraries) love writing files...
                                # read_only_root_filesystem=True,
                                capabilities={"add": ["IPC_LOCK"]},
                            ),
                            command=[
                                "chutes",
                                "run",
                                chute.ref_str,
                                "--port",
                                "8000",
                                "--graval-seed",
                                str(server.seed),
                                "--miner-ss58",
                                settings.miner_ss58,
                                "--validator-ss58",
                                server.validator,
                            ],
                            ports=[{"containerPort": 8000}],
                            readiness_probe=V1Probe(
                                _exec=V1ExecAction(
                                    command=[
                                        "/bin/sh",
                                        "-c",
                                        "curl -f http://127.0.0.1:8000/_alive || exit 1",
                                    ]
                                ),
                                initial_delay_seconds=15,
                                period_seconds=15,
                                timeout_seconds=1,
                                success_threshold=1,
                                failure_threshold=60,
                            ),
                        )
                    ],
                ),
            ),
        ),
    )


def build_chute_service(deployment_id, chute: Chute):
    return V1Service(
        metadata=V1ObjectMeta(
            name=f"chute-service-{deployment_id}",
            labels={
                "chutes/deployment-id": deployment_id,
                "chutes/chute": "true",
                "chutes/chute-id": chute.chute_id,
                "chutes/version": chute.version,
            },
        ),
        spec=V1ServiceSpec(
            type="NodePort",
            external_traffic_policy="Local",
            selector={
                "chutes/deployment-id": deployment_id,
            },
            ports=[V1ServicePort(port=8000, target_port=8000, protocol="TCP")],
        ),
    )
