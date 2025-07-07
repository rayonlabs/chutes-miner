"""
Server uility functions.
"""

import time
import math
import backoff
import aiohttp
import asyncio
import traceback
import chutes_common.constants as cst
from loguru import logger
from kubernetes.client import (
    V1Node,
    V1Deployment,
    V1Service,
    V1ObjectMeta,
    V1DeploymentSpec,
    V1PodTemplateSpec,
    V1PodSpec,
    V1Container,
    V1ResourceRequirements,
    V1ServiceSpec,
    V1ServicePort,
    V1Probe,
    V1ExecAction,
    V1EnvVar,
)
from sqlalchemy import update, select
from sqlalchemy.exc import IntegrityError
from typing import Tuple, Dict, List
from chutes_common.auth import sign_request
from chutes_miner.api.config import settings, Validator, validator_by_hotkey
from chutes_miner.api.k8s.constants import GRAVAL_DEPLOY_PREFIX, GRAVAL_SVC_PREFIX
from chutes_miner.api.k8s.operator import K8sOperator
from chutes_miner.api.util import sse_message
from chutes_miner.api.database import get_session
from chutes_miner.api.server.schemas import Server, ServerArgs
from chutes_miner.api.gpu.schemas import GPU
from chutes_miner.api.exceptions import (
    DuplicateServer,
    NonEmptyServer,
    GPUlessServer,
    GraValBootstrapFailure,
)


@backoff.on_exception(
    backoff.constant,
    Exception,
    jitter=None,
    interval=3,
    max_tries=5,
)
async def _fetch_devices(url):
    """
    Query the GraVal bootstrap API for device info.
    """
    nonce = str(int(time.time()))
    headers = {
        cst.MINER_HEADER: settings.miner_ss58,
        cst.VALIDATOR_HEADER: settings.miner_ss58,
        cst.NONCE_HEADER: nonce,
    }
    headers[cst.SIGNATURE_HEADER] = settings.miner_keypair.sign(
        ":".join([settings.miner_ss58, settings.miner_ss58, nonce, "graval"])
    ).hex()
    logger.debug(f"Authenticating: {headers}")
    async with aiohttp.ClientSession(raise_for_status=True) as session:
        async with session.get(url, headers=headers, timeout=5) as response:
            return (await response.json())["devices"]


async def gather_gpu_info(
    server_id: str,
    validator: str,
    node_object: V1Node,
    graval_deployment: V1Deployment,
    graval_service: V1Service,
) -> List[GPU]:
    """
    Wait for the graval bootstrap deployments to be ready, then gather the device info.
    """
    deployment_name = graval_deployment.metadata.name
    namespace = graval_deployment.metadata.namespace or "chutes"
    expected_gpu_count = int(node_object.metadata.labels.get("nvidia.com/gpu.count", "0"))
    gpu_short_ref = node_object.metadata.labels.get("gpu-short-ref")
    if not gpu_short_ref:
        raise GraValBootstrapFailure("Node does not have required gpu-short-ref label!")

    # Wait for the bootstrap deployment to be ready.
    start_time = time.time()
    deployment_ready = False
    try:
        for event in K8sOperator().watch_deployments(
            namespace=namespace,
            field_selector=f"metadata.name={deployment_name}",
            timeout=settings.graval_bootstrap_timeout,
        ):
            deployment = event.object
            if deployment.status.conditions:
                for condition in deployment.status.conditions:
                    if condition.type == "Failed" and condition.status == "True":
                        raise GraValBootstrapFailure(f"Deployment failed: {condition.message}")
            if (deployment.status.ready_replicas or 0) == deployment.spec.replicas:
                deployment_ready = True
                break
            if (delta := time.time() - start_time) >= settings.graval_bootstrap_timeout:
                raise TimeoutError(f"GraVal bootstrap deployment not ready after {delta} seconds!")
            await asyncio.sleep(1)
    except Exception as exc:
        raise GraValBootstrapFailure(f"Error waiting for graval bootstrap deployment: {exc}")
    if not deployment_ready:
        raise GraValBootstrapFailure("GraVal bootstrap deployment never reached ready state.")

    # Configure our validation host/port.
    node_port = None
    node_ip = node_object.metadata.labels.get("chutes/external-ip")
    for port in graval_service.spec.ports:
        if port.node_port:
            node_port = port.node_port
            break

    # Query the GPU information.
    devices = None
    try:
        devices = await _fetch_devices(f"http://{node_ip}:{node_port}/devices")
        assert devices
        assert len(devices) == expected_gpu_count
    except Exception as exc:
        raise GraValBootstrapFailure(
            f"Failed to fetch devices from GraVal bootstrap: {node_ip}:{node_port}/devices: {exc}"
        )

    # Store inventory.
    gpus = []
    async with get_session() as session:
        for device_id in range(len(devices)):
            device_info = devices[device_id]
            gpu = GPU(
                server_id=server_id,
                validator=validator,
                gpu_id=device_info["uuid"],
                device_info=device_info,
                model_short_ref=gpu_short_ref,
                verified=False,
            )
            session.add(gpu)
            gpus.append(gpu)
        await session.commit()
        for idx in range(len(gpus)):
            await session.refresh(gpus[idx])
    return gpus


async def deploy_graval(
    node_object: V1Node, validator_hotkey: str
) -> Tuple[V1Deployment, V1Service]:
    """
    Create a deployment of the GraVal base validation service on a node.
    """
    node_name = node_object.metadata.name
    node_labels = node_object.metadata.labels or {}

    # Double check that we don't already have chute deployments.
    existing_deployments = K8sOperator().get_deployments(
        label_selector="chute/chute=true,app=graval"
    )
    if any(
        [dep for dep in existing_deployments.items if dep.spec.template.spec.node_name == node_name]
    ):
        raise NonEmptyServer(
            f"Kubnernetes node {node_name} already has one or more chute and/or graval deployments."
        )

    # Make sure the GPU labels are set.
    gpu_count = node_labels.get("nvidia.com/gpu.count", "0")
    if not gpu_count or not gpu_count.isdigit() or not 0 < (gpu_count := int(gpu_count)) <= 10:
        raise GPUlessServer(
            f"Kubernetes node {node_name} nvidia.com/gpu.count label missing or invalid: {node_labels.get('nvidia.com/gpu.count')}"
        )

    # Create the deployment.
    nice_name = node_name.replace(".", "-")
    deployment = V1Deployment(
        metadata=V1ObjectMeta(
            name=f"{GRAVAL_DEPLOY_PREFIX}-{nice_name}",
            labels={
                "app": "graval",
                "chute/chute": "false",
                "graval-node": node_name,
            },
        ),
        spec=V1DeploymentSpec(
            replicas=1,
            selector={"matchLabels": {"app": "graval", "graval-node": node_name}},
            template=V1PodTemplateSpec(
                metadata=V1ObjectMeta(labels={"app": "graval", "graval-node": node_name}),
                spec=V1PodSpec(
                    node_name=node_name,
                    runtime_class_name=settings.nvidia_runtime,
                    containers=[
                        V1Container(
                            name="graval",
                            image=settings.graval_bootstrap_image,
                            image_pull_policy="Always",
                            env=[
                                V1EnvVar(
                                    name="VALIDATOR_WHITELIST",
                                    value=validator_hotkey,
                                ),
                                V1EnvVar(
                                    name="MINER_HOTKEY_SS58",
                                    value=settings.miner_ss58,
                                ),
                            ],
                            resources=V1ResourceRequirements(
                                requests={
                                    "cpu": str(gpu_count),
                                    "memory": "8Gi",
                                    "nvidia.com/gpu": str(gpu_count),
                                },
                                limits={
                                    "cpu": str(gpu_count),
                                    "memory": "8Gi",
                                    "nvidia.com/gpu": str(gpu_count),
                                },
                            ),
                            ports=[{"containerPort": 8000}],
                            readiness_probe=V1Probe(
                                _exec=V1ExecAction(
                                    command=[
                                        "/bin/sh",
                                        "-c",
                                        "curl -f http://127.0.0.1:8000/ping || exit 1",
                                    ]
                                ),
                                initial_delay_seconds=15,
                                period_seconds=10,
                                timeout_seconds=1,
                                success_threshold=1,
                                failure_threshold=3,
                            ),
                        )
                    ],
                ),
            ),
        ),
    )

    # And the service that exposes it.
    service = V1Service(
        metadata=V1ObjectMeta(
            name=f"{GRAVAL_SVC_PREFIX}-{nice_name}",
            labels={"app": "graval", "graval-node": node_name},
        ),
        spec=V1ServiceSpec(
            type="NodePort",
            selector={"app": "graval", "graval-node": node_name},
            ports=[V1ServicePort(port=8000, target_port=8000, protocol="TCP")],
        ),
    )

    # Deploy!
    return await K8sOperator().deploy_graval(node_object, deployment, service)


async def track_server(
    validator: str, hourly_cost: float, node_object: V1Node, add_labels: Dict[str, str] = None
) -> Tuple[V1Node, Server]:
    """
    Track a new kubernetes (worker/GPU) node in our inventory.
    """
    if not node_object.metadata or not node_object.metadata.name:
        raise ValueError("Node object must have metadata and name")

    # Make sure the labels (in kubernetes) are up-to-date.
    current_labels = node_object.metadata.labels or {}
    labels_to_add = {}
    for key, value in (add_labels or {}).items():
        if key not in current_labels or current_labels[key] != value:
            labels_to_add[key] = value
    if labels_to_add:
        current_labels.update(labels_to_add)
        body = {"metadata": {"labels": current_labels}}
        node_object = K8sOperator().patch_node(name=node_object.metadata.name, body=body)
    labels = current_labels

    # Extract node information from kubernetes meta.
    name = node_object.metadata.name
    server_id = node_object.metadata.uid
    ip_address = node_object.metadata.labels.get("chutes/external-ip")

    # Determine node status.
    status = "Unknown"
    if node_object.status and node_object.status.conditions:
        for condition in node_object.status.conditions:
            if condition.type == "Ready":
                status = "Ready" if condition.status == "True" else "NotReady"
                break
    if status != "Ready":
        raise ValueError(f"Node is not yet ready [{status=}]")

    # Calculate CPU/RAM per GPU for allocation purposes.
    gpu_count = int(node_object.status.capacity["nvidia.com/gpu"])
    gpu_mem_mb = int(node_object.metadata.labels.get("nvidia.com/gpu.memory", "32"))
    gpu_mem_gb = int(gpu_mem_mb / 1024)
    cpu_count = (
        int(node_object.status.capacity["cpu"]) - 2
    )  # leave 2 CPUs for incidentals, daemon sets, etc.
    cpu_per_gpu = 1 if cpu_count <= gpu_count else min(4, math.floor(cpu_count / gpu_count))
    raw_mem = node_object.status.capacity["memory"]
    if raw_mem.endswith("Ki"):
        total_memory_gb = int(int(raw_mem.replace("Ki", "")) / 1024 / 1024) - 6
    elif raw_mem.endswith("Mi"):
        total_memory_gb = int(int(raw_mem.replace("Mi", "")) / 1024) - 6
    elif raw_mem.endswith("Gi"):
        total_memory_gb = int(raw_mem.replace("Gi", "")) - 6
    memory_per_gpu = (
        1
        if total_memory_gb <= gpu_count
        else min(gpu_mem_gb, math.floor(total_memory_gb * 0.8 / gpu_count))
    )

    # Track the server in our inventory.
    async with get_session() as session:
        server = Server(
            server_id=node_object.metadata.uid,
            validator=validator,
            name=name,
            ip_address=ip_address,
            status=status,
            labels=labels,
            gpu_count=gpu_count,
            cpu_per_gpu=cpu_per_gpu,
            memory_per_gpu=memory_per_gpu,
            hourly_cost=hourly_cost,
        )
        session.add(server)
        try:
            await session.commit()
        except IntegrityError as exc:
            if "UniqueViolationError" in str(exc):
                raise DuplicateServer(
                    f"Server {server_id=} {name=} {server_id=} already in database."
                )
            else:
                raise
        await session.refresh(server)

    return node_object, server


@backoff.on_exception(
    backoff.constant,
    Exception,
    jitter=None,
    interval=3,
    max_tries=5,
)
async def _advertise_nodes(validator: Validator, gpus: List[GPU]):
    """
    Post GPU information to one validator, with retries.
    """
    async with aiohttp.ClientSession() as session:
        device_infos = [
            {
                **gpus[idx].device_info,
                **dict(
                    device_index=idx,
                    gpu_identifier=gpus[idx].model_short_ref,
                    verification_host=gpus[idx].server.ip_address,
                    verification_port=gpus[idx].server.verification_port,
                ),
            }
            for idx in range(len(gpus))
        ]
        headers, payload_string = sign_request(payload={"nodes": device_infos})
        async with session.post(
            f"{validator.api}/nodes/", data=payload_string, headers=headers
        ) as response:
            response_text = await response.text()
            assert response.status == 202, response_text
            data = await response.json()
            nodes = data.get("nodes")
            task_id = data.get("task_id")
            assert len(nodes) == len(gpus)
            assert task_id
            logger.success(
                f"Successfully advertised {len(gpus)} to {validator.hotkey} via {validator.api}"
            )
            return task_id, nodes


@backoff.on_exception(
    backoff.constant,
    Exception,
    jitter=None,
    interval=3,
    max_tries=5,
)
async def check_verification_task_status(validator: Validator, task_id: str) -> bool:
    """
    Check the GPU verification task status.
    """
    async with aiohttp.ClientSession(raise_for_status=True) as session:
        headers, _ = sign_request(purpose="graval")
        async with session.get(
            f"{validator.api}/nodes/verification_status",
            params={"task_id": task_id},
            headers=headers,
        ) as response:
            data = await response.json()
            if (status := data.get("status")) == "pending":
                return None
            if status in ["error", "failed"]:
                return False
            return True


async def bootstrap_server(node_object: V1Node, server_args: ServerArgs):
    """
    Bootstrap a server from start to finish, yielding SSEs for miner to track status.
    """
    started_at = time.time()

    async def _cleanup(delete_node: bool = True):
        await K8sOperator().cleanup_graval(node_object)

        node_uid = node_object.metadata.uid
        node_name = node_object.metadata.name.replace(".", "-")
        if delete_node:
            logger.info(f"Purging failed server: {node_name=} {node_uid=}")
            async with get_session() as session:
                node = (
                    (await session.execute(select(Server).where(Server.server_id == node_uid)))
                    .unique()
                    .scalar_one_or_none()
                )
                if node:
                    await session.delete(node)
                await session.commit()

    yield sse_message(
        f"attempting to add node server_id={node_object.metadata.uid} to inventory...",
    )
    seed = None
    try:
        node, server = await track_server(
            server_args.validator,
            server_args.hourly_cost,
            node_object,
            add_labels={
                "gpu-short-ref": server_args.gpu_short_ref,
                "chutes/validator": server_args.validator,
                "chutes/worker": "true",
            },
        )

        # Great, now it's in our database, but we need to startup graval so the validator can check the GPUs.
        yield sse_message(
            f"server with server_id={node_object.metadata.uid} now tracked in database, provisioning graval...",
        )
        graval_dep, graval_svc = await deploy_graval(node, server_args.validator)

        # Excellent, now gather the GPU info.
        yield sse_message(
            "graval bootstrap deployment/service created, gathering device info...",
        )
        gpus = await gather_gpu_info(
            server.server_id, server_args.validator, node, graval_dep, graval_svc
        )

        # Beautiful, tell the validators about it.
        model_name = gpus[0].device_info["name"]
        yield sse_message(
            f"discovered {len(gpus)} GPUs [{model_name=}] on node, advertising node to {len(settings.validators)} validator(s)...",
        )
        validator = validator_by_hotkey(server_args.validator)
        yield sse_message(
            f"advertising node to {validator.hotkey} via {validator.api}...",
        )
        validator_nodes = None
        task_id = None
        try:
            task_id, validator_nodes = await _advertise_nodes(validator, gpus)
        except Exception as exc:
            yield sse_message(
                f"failed to advertising node to {validator.hotkey} via {validator.api}: {exc}",
            )
            raise
        assert len(set(node["seed"] for node in validator_nodes)) == 1, (
            f"more than one seed produced from {validator.hotkey}!"
        )
        if not seed:
            seed = validator_nodes[0]["seed"]
        else:
            assert seed == validator_nodes[0]["seed"], (
                f"validators produced differing seeds {seed} vs {validator_nodes[0]['seed']}"
            )
        yield sse_message(
            f"successfully advertised node {node_object.metadata.uid} to validator {validator.hotkey}, received seed: {seed}"
        )
        async with get_session() as session:
            await session.execute(
                update(Server)
                .where(Server.server_id == node_object.metadata.uid)
                .values({"seed": seed})
            )
            await session.commit()

        # Wait for verification from this validator.
        while (status := await check_verification_task_status(validator, task_id)) is None:
            yield sse_message(
                f"waiting for validator {validator.hotkey} to finish GPU verification..."
            )
            await asyncio.sleep(1)
        if status:
            yield sse_message(
                f"validator {validator.hotkey} has successfully performed GPU verification"
            )
        else:
            error_message = f"GPU verification failed for {validator.hotkey}, aborting!"
            yield sse_message(error_message)
            raise GraValBootstrapFailure(error_message)

    except Exception as exc:
        error_message = (
            f"unhandled exception bootstrapping new node: {exc}\n{traceback.format_exc()}"
        )
        logger.error(error_message)
        yield sse_message(error_message)
        await _cleanup(delete_node=True)
        raise
    finally:
        await _cleanup(delete_node=False)

    # Astonishing, everything worked.
    async with get_session() as session:
        await session.execute(
            update(GPU).where(GPU.server_id == node_object.metadata.uid).values({"verified": True})
        )
        await session.commit()
    yield sse_message(f"completed server bootstrapping in {time.time() - started_at} seconds!")
