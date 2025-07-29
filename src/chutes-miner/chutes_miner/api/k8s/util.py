from typing import Any, Optional
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
    V1Job,
    V1JobSpec
)

from chutes_common.schemas.chute import Chute
from chutes_miner.api.k8s.constants import CHUTE_DEPLOY_PREFIX, CHUTE_SVC_PREFIX
from chutes_common.schemas.server import Server
from chutes_miner.api.config import settings


def build_chute_job(deployment_id, chute: Chute, server: Server, service: V1Service, 
    gpu_uuids: list[str], probe_port: int, token: Optional[str] = None, 
    config_id: Optional[str] = None, disk_gb: int  = 10
) -> V1Job:
    cpu = str(server.cpu_per_gpu * chute.gpu_count)
    ram = str(server.memory_per_gpu * chute.gpu_count) + "Gi"
    code_uuid = str(uuid.uuid5(uuid.NAMESPACE_OID, f"{chute.chute_id}::{chute.version}"))
    deployment_labels = {
        "chutes/deployment-id": deployment_id,
        "chutes/chute": "true",
        "chutes/chute-id": chute.chute_id,
        "chutes/version": chute.version,
    }

    if config_id:
        deployment_labels["chutes/config-id"] = config_id

        # Command will vary depending on chutes version.
    extra_env = []
    command = [
        "chutes",
        "run",
        chute.ref_str,
        "--port",
        "8000",
    ]
    if not token:
        command += ["--graval-seed", str(server.seed)]
    else:
        extra_env += [
            V1EnvVar(
                name="CHUTES_LAUNCH_JWT",
                value=token,
            ),
            V1EnvVar(
                name="CHUTES_EXTERNAL_HOST",
                value=server.ip_address,
            ),
        ]

    # Port mappings must be in the environment variables.
    unique_ports = [8000, 8001]
    for port_object in service.spec.ports[2:]:
        proto = (port_object.protocol or "TCP").upper()
        extra_env.append(
            V1EnvVar(
                name=f"CHUTES_PORT_{proto}_{port_object.port}",
                value=str(port_object.node_port),
            )
        )
        if port_object.port not in unique_ports:
            unique_ports.append(port_object.port)

    # Tack on the miner/validator addresses.
    command += [
        "--miner-ss58",
        settings.miner_ss58,
        "--validator-ss58",
        server.validator,
    ]

    return V1Job(
        metadata=V1ObjectMeta(
            name=f"{CHUTE_DEPLOY_PREFIX}-{deployment_id}",
            labels=deployment_labels,
        ),
        spec=V1JobSpec(
            parallelism=1,
            completions=1,
            backoff_limit=0,
            ttl_seconds_after_finished=300,
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
                    restart_policy="Never",
                    node_name=server.name,  ## Start here
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
                                path=f"/var/snap/cache/{chute.chute_id}",
                                type="DirectoryOrCreate",
                            ),
                        ),
                        V1Volume(
                            name="raw-cache",
                            host_path=V1HostPathVolumeSource(
                                path="/var/snap/cache",
                                type="DirectoryOrCreate",
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
                            empty_dir=V1EmptyDirVolumeSource(size_limit=f"{disk_gb}Gi"),
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
                                    name="CLEANUP_EXCLUDE",
                                    value=chute.chute_id,
                                ),
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
                                V1VolumeMount(name="raw-cache", mount_path="/cache"),
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
                                    name="NVIDIA_VISIBLE_DEVICES",
                                    value=",".join(gpu_uuids),
                                ),
                                V1EnvVar(
                                    name="CHUTES_PORT_PRIMARY",
                                    value=str(service.spec.ports[0].node_port),
                                ),
                                V1EnvVar(
                                    name="CHUTES_PORT_LOGGING",
                                    value=str(service.spec.ports[1].node_port),
                                ),
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
                                    name="NCCL_SOCKET_IFNAME",
                                    value="lo",
                                ),
                                V1EnvVar(
                                    name="NCCL_SOCKET_FAMILY",
                                    value="AF_INET",
                                ),
                                V1EnvVar(name="HF_HOME", value="/cache"),
                                V1EnvVar(name="CIVITAI_HOME", value="/cache/civitai"),
                            ] + extra_env,
                            resources=V1ResourceRequirements(
                                requests={
                                    "cpu": cpu,
                                    "memory": ram,
                                    "ephemeral-storage": f"{disk_gb}Gi",
                                },
                                limits={
                                    "cpu": cpu,
                                    "memory": ram,
                                    "ephemeral-storage": f"{disk_gb}Gi",
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
                            command=command,
                            ports=[{"containerPort": port} for port in unique_ports],
                            readiness_probe=V1Probe(
                                _exec=V1ExecAction(
                                    command=[
                                        "/bin/sh",
                                        "-c",
                                        f"curl -f http://127.0.0.1:{probe_port}/_alive || exit 1",
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


def build_chute_service(chute: Chute, deployment_id: str, extra_service_ports: list[dict[str, Any]] = []):
    return V1Service(
        metadata=V1ObjectMeta(
            name=f"{CHUTE_SVC_PREFIX}-{deployment_id}",
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
            ports=[
                V1ServicePort(port=8000, target_port=8000, protocol="TCP", name="chute-8000"),
                V1ServicePort(port=8001, target_port=8001, protocol="TCP", name="chute-8001"),
            ]
            + [
                V1ServicePort(
                    port=svc["port"],
                    target_port=svc["port"],
                    protocol=svc["proto"],
                    name=f"chute-{svc['port']}",
                )
                for svc in extra_service_ports
            ],
        ),
    )
