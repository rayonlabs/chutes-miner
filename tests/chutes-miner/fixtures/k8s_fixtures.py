# Fixtures for commonly used objects
from re import L
from unittest.mock import MagicMock, patch

import pytest

from chutes_common.schemas.chute import Chute
from chutes_common.schemas.gpu import GPU
from chutes_common.schemas.server import Server

import uuid
import random
from datetime import datetime, timezone
import json
from dateutil.tz import tzutc

@pytest.fixture()
def mock_k8s_core_client():
    # Create a list of paths where k8s_core_client is imported
    import_paths = ["chutes_miner.api.k8s.operator.k8s_core_client"]

    # Create a single mock object
    mock_client = MagicMock()
    # mock_client.list_node.return_value = MagicMock(items=None)

    # Create and start patches for each import path, all returning the same mock
    patches = []
    for path in import_paths:
        patcher = patch(path, return_value=mock_client)
        patcher.start()
        patches.append(patcher)

    # Yield the shared mock for use in tests
    yield mock_client

    # Stop all patches when done
    for patcher in patches:
        patcher.stop()


@pytest.fixture()
def mock_k8s_app_client():
    import_paths = ["chutes_miner.api.k8s.operator.k8s_app_client"]

    # Create a single mock object
    mock_client = MagicMock()
    # mock_client.list_node.return_value = MagicMock(items=None)

    # Create and start patches for each import path, all returning the same mock
    patches = []
    for path in import_paths:
        patcher = patch(path, return_value=mock_client)
        patcher.start()
        patches.append(patcher)

    # Yield the shared mock for use in tests
    yield mock_client

    # Stop all patches when done
    for patcher in patches:
        patcher.stop()

@pytest.fixture()
def mock_k8s_batch_client():
    import_paths = ["chutes_miner.api.k8s.operator.k8s_batch_client"]

    # Create a single mock object
    mock_client = MagicMock()
    # mock_client.list_node.return_value = MagicMock(items=None)

    # Create and start patches for each import path, all returning the same mock
    patches = []
    for path in import_paths:
        patcher = patch(path, return_value=mock_client)
        patcher.start()
        patches.append(patcher)

    # Yield the shared mock for use in tests
    yield mock_client

    # Stop all patches when done
    for patcher in patches:
        patcher.stop()

@pytest.fixture()
def mock_k8s_api_client():
    client = MagicMock()
    yield client

# @pytest.fixture(autouse=True)
# def mock_k8s_api_client():
#     import_paths = ["chutes_miner.api.k8s.operator.k8s_api_client"]

#     # Create a single mock object
#     client = MagicMock()
#     # client.call_api = MagicMock(wraps=client.call_api)
#     # mock_client.list_node.return_value = MagicMock(items=None)

#     # Create and start patches for each import path, all returning the same mock
#     patches = []
#     for path in import_paths:
#         patcher = patch(path, return_value=client)
#         patcher.start()
#         patches.append(patcher)

#     # Yield the shared mock for use in tests
#     yield client

#     # Stop all patches when done
#     for patcher in patches:
#         patcher.stop()

@pytest.fixture
def mock_k8s_client_manager(mock_k8s_api_client, mock_k8s_core_client, mock_k8s_app_client, mock_k8s_batch_client):
    with patch("chutes_miner.api.k8s.operator.KubernetesMultiClusterClientManager") as mock_manager_class:
        mock_manager = MagicMock()
        mock_manager.get_api_client.return_value = mock_k8s_api_client
        mock_manager.get_app_client.return_value = mock_k8s_app_client
        mock_manager.get_core_client.return_value = mock_k8s_core_client
        mock_manager.get_batch_client.return_value = mock_k8s_batch_client
        mock_manager_class.return_value = mock_manager
        yield mock_manager


@pytest.fixture
def sample_server():
    server = Server(
        server_id="test-server-id",
        name="test-node",
        validator="TEST123",
        ip_address="192.168.1.100",
        cpu_per_gpu=4,
        memory_per_gpu=16,
        seed=12345,
        deployments=[],
        gpus=[
            GPU(gpu_id=f"{uuid.uuid4()}", server_id="test-server-id", verified=True) for i in range(4)
        ]
    )


    return server


@pytest.fixture
def sample_chute():
    return Chute(
        chute_id="test-chute-id",
        version="1.0.0",
        filename="app.py",
        code="print('Hello World')",
        image="test/image:latest",
        gpu_count=2,
        ref_str="test-ref-str",
    )


@pytest.fixture
def mock_watch():
    with patch("chutes_miner.api.k8s.operator.watch.Watch") as mock_watch:
        watch_instance = MagicMock()
        mock_watch.return_value = watch_instance
        yield watch_instance


@pytest.fixture
def mock_deployment():
    """
    Create a mock K8s deployment object with realistic structure.

    Returns a fully configured mock deployment with status fields, metadata, and spec.
    """
    deployment = MagicMock()

    # Metadata
    deployment.metadata = MagicMock()
    deployment.metadata.name = "chute-test-123"
    deployment.metadata.namespace = "test-namespace"
    deployment.metadata.uid = "d-12345678-1234-1234-1234-123456789012"
    deployment.metadata.creation_timestamp = "2023-04-01T12:00:00Z"
    deployment.metadata.labels = {
        "chutes/deployment-id": "test-123",
        "chutes/chute": "true",
        "chutes/chute-id": "chute-abc",
        "chutes/version": "1.0.0",
        "squid-access": "true",
    }
    deployment.metadata.annotations = {"deployment.kubernetes.io/revision": "1"}

    # Spec
    deployment.spec = MagicMock()
    deployment.spec.replicas = 1
    deployment.spec.selector = MagicMock()
    deployment.spec.selector.match_labels = {"chutes/deployment-id": "test-123"}
    deployment.spec.template = MagicMock()
    deployment.spec.template.metadata = MagicMock()
    deployment.spec.template.metadata.labels = deployment.metadata.labels.copy()
    deployment.spec.template.spec = MagicMock()
    deployment.spec.template.spec.node_selector = {"chutes/worker": "true"}
    deployment.spec.template.spec.containers = [MagicMock()]
    deployment.spec.template.spec.containers[0].name = "chute"
    deployment.spec.template.spec.containers[
        0
    ].image = "test-validator.localregistry.chutes.ai:5000/test-image:latest"
    deployment.spec.template.spec.containers[0].resources = MagicMock()
    deployment.spec.template.spec.containers[0].resources.requests = {
        "cpu": "8",
        "memory": "32Gi",
        "nvidia.com/gpu": "2",
    }
    deployment.spec.template.spec.containers[0].resources.limits = {
        "cpu": "8",
        "memory": "32Gi",
        "nvidia.com/gpu": "2",
    }
    deployment.spec.template.spec.node_name = "node-1"

    # Status
    deployment.status = MagicMock()
    deployment.status.replicas = 1
    deployment.status.ready_replicas = 1
    deployment.status.updated_replicas = 1
    deployment.status.available_replicas = 1
    deployment.status.unavailable_replicas = None
    deployment.status.conditions = [
        MagicMock(type="Available", status="True"),
        MagicMock(type="Progressing", status="True"),
    ]
    deployment.status.observed_generation = 1

    return deployment


@pytest.fixture
def mock_pod():
    """
    Create a mock K8s pod object with realistic structure.

    Returns a fully configured mock pod with status fields, metadata, and spec.
    """
    pod = MagicMock()

    # Metadata
    pod.metadata = MagicMock()
    pod.metadata.name = "chute-test-123-69d74d8dcf-xr5pq"
    pod.metadata.namespace = "test-namespace"
    pod.metadata.uid = "p-98765432-4321-4321-4321-210987654321"
    pod.metadata.creation_timestamp = "2023-04-01T12:01:00Z"
    pod.metadata.labels = {
        "chutes/deployment-id": "test-123",
        "chutes/chute": "true",
        "chutes/chute-id": "chute-abc",
        "chutes/version": "1.0.0",
        "pod-template-hash": "69d74d8dcf",
    }
    pod.metadata.owner_references = [
        MagicMock(
            api_version="apps/v1",
            kind="ReplicaSet",
            name="chute-test-123-69d74d8dcf",
            uid="rs-11112222-3333-4444-5555-666677778888",
        )
    ]

    # Spec
    pod.spec = MagicMock()
    pod.spec.node_name = "node-1"
    pod.spec.containers = [MagicMock()]
    pod.spec.containers[0].name = "chute"
    pod.spec.containers[0].image = "test-validator.localregistry.chutes.ai:5000/test-image:latest"
    pod.spec.containers[0].ports = [MagicMock(container_port=8000)]
    pod.spec.containers[0].resources = MagicMock()
    pod.spec.containers[0].resources.requests = {
        "cpu": "8",
        "memory": "32Gi",
        "nvidia.com/gpu": "2",
    }
    pod.spec.containers[0].resources.limits = {"cpu": "8", "memory": "32Gi", "nvidia.com/gpu": "2"}
    pod.spec.volumes = [
        MagicMock(name="code"),
        MagicMock(name="cache"),
        MagicMock(name="tmp"),
        MagicMock(name="shm"),
    ]
    pod.spec.restart_policy = "Always"
    pod.spec.termination_grace_period_seconds = 30
    pod.spec.dns_policy = "ClusterFirst"
    pod.spec.service_account_name = "default"
    pod.spec.service_account = "default"
    pod.spec.node_selector = {"chutes/worker": "true"}
    pod.spec.security_context = {}
    pod.spec.scheduler_name = "default-scheduler"
    pod.spec.tolerations = [MagicMock()]
    pod.spec.priority = 0
    pod.spec.priority_class_name = "normal"
    pod.spec.host_network = False

    # Status
    pod.status = MagicMock()
    pod.status.phase = "Running"
    pod.status.conditions = [
        MagicMock(type="Initialized", status="True"),
        MagicMock(type="Ready", status="True"),
        MagicMock(type="ContainersReady", status="True"),
        MagicMock(type="PodScheduled", status="True"),
    ]
    pod.status.host_ip = "192.168.1.10"
    pod.status.pod_ip = "10.244.1.15"
    pod.status.pod_ips = [MagicMock(ip="10.244.1.15")]
    pod.status.start_time = "2023-04-01T12:01:30Z"
    pod.status.container_statuses = [MagicMock()]
    pod.status.container_statuses[0].name = "chute"
    pod.status.container_statuses[0].state = MagicMock()
    pod.status.container_statuses[0].state.running = MagicMock()
    pod.status.container_statuses[0].state.running.started_at = "2023-04-01T12:01:45Z"
    pod.status.container_statuses[0].state.waiting = None
    pod.status.container_statuses[0].state.terminated = None
    pod.status.container_statuses[0].last_state = MagicMock()
    pod.status.container_statuses[0].last_state.running = None
    pod.status.container_statuses[0].last_state.waiting = None
    pod.status.container_statuses[0].last_state.terminated = None
    pod.status.container_statuses[0].ready = True
    pod.status.container_statuses[0].restart_count = 0
    pod.status.container_statuses[
        0
    ].image = "test-validator.localregistry.chutes.ai:5000/test-image:latest"
    pod.status.container_statuses[
        0
    ].image_id = "docker-pullable://test-validator.localregistry.chutes.ai:5000/test-image@sha256:1234567890abcdef"
    pod.status.container_statuses[
        0
    ].container_id = "containerd://1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"
    pod.status.qos_class = "Guaranteed"

    # Helper methods to simulate real pod behavior
    def set_running():
        pod.status.phase = "Running"
        pod.status.container_statuses[0].state.running = MagicMock()
        pod.status.container_statuses[0].state.running.started_at = "2023-04-01T12:01:45Z"
        pod.status.container_statuses[0].state.waiting = None
        pod.status.container_statuses[0].state.terminated = None
        pod.status.container_statuses[0].ready = True
        # Set all conditions to True
        for condition in pod.status.conditions:
            condition.status = "True"

    def set_pending():
        pod.status.phase = "Pending"
        pod.status.container_statuses[0].state.running = None
        pod.status.container_statuses[0].state.waiting = MagicMock()
        pod.status.container_statuses[0].state.waiting.reason = "ContainerCreating"
        pod.status.container_statuses[0].state.terminated = None
        pod.status.container_statuses[0].ready = False
        # Set Ready condition to False
        for condition in pod.status.conditions:
            if condition.type == "Ready" or condition.type == "ContainersReady":
                condition.status = "False"

    def set_error(
        reason="CrashLoopBackOff", message="Back-off restarting failed container", exit_code=1
    ):
        pod.status.phase = "Running"  # Pods in CrashLoopBackOff still have Running phase
        pod.status.container_statuses[0].ready = False
        pod.status.container_statuses[0].restart_count += 1

        # Set current state to waiting with crash reason
        pod.status.container_statuses[0].state.running = None
        pod.status.container_statuses[0].state.waiting = MagicMock()
        pod.status.container_statuses[0].state.waiting.reason = reason
        pod.status.container_statuses[0].state.waiting.message = message

        # Set last state to terminated with error
        pod.status.container_statuses[0].last_state.terminated = MagicMock()
        pod.status.container_statuses[0].last_state.terminated.exit_code = exit_code
        pod.status.container_statuses[0].last_state.terminated.reason = "Error"
        pod.status.container_statuses[0].last_state.terminated.started_at = "2023-04-01T12:01:45Z"
        pod.status.container_statuses[0].last_state.terminated.finished_at = "2023-04-01T12:01:50Z"

        # Set Ready condition to False
        for condition in pod.status.conditions:
            if condition.type == "Ready" or condition.type == "ContainersReady":
                condition.status = "False"

    def set_terminating():
        pod.status.phase = "Running"
        pod.metadata.deletion_timestamp = "2023-04-01T13:00:00Z"
        # Add a finalizer to make it look like it's still terminating
        pod.metadata.finalizers = ["kubernetes.io/psp"]

    # Attach these helper methods to the mock
    pod.set_running = set_running
    pod.set_pending = set_pending
    pod.set_error = set_error
    pod.set_terminating = set_terminating

    # Define to_dict methods for state objects to match real K8s behavior
    pod.status.container_statuses[0].state.to_dict = lambda: {
        "running": pod.status.container_statuses[0].state.running.to_dict()
        if pod.status.container_statuses[0].state.running
        else None,
        "waiting": pod.status.container_statuses[0].state.waiting.to_dict()
        if pod.status.container_statuses[0].state.waiting
        else None,
        "terminated": pod.status.container_statuses[0].state.terminated.to_dict()
        if pod.status.container_statuses[0].state.terminated
        else None,
    }

    if pod.status.container_statuses[0].state.running:
        pod.status.container_statuses[0].state.running.to_dict = lambda: {
            "startedAt": pod.status.container_statuses[0].state.running.started_at
        }

    # These methods will be created if the states are set via the helper methods
    if (
        hasattr(pod.status.container_statuses[0].state, "waiting")
        and pod.status.container_statuses[0].state.waiting
    ):
        pod.status.container_statuses[0].state.waiting.to_dict = lambda: {
            "reason": pod.status.container_statuses[0].state.waiting.reason,
            "message": pod.status.container_statuses[0].state.waiting.message,
        }

    # Same for last_state
    pod.status.container_statuses[0].last_state.to_dict = lambda: {
        "running": pod.status.container_statuses[0].last_state.running.to_dict()
        if pod.status.container_statuses[0].last_state.running
        else None,
        "waiting": pod.status.container_statuses[0].last_state.waiting.to_dict()
        if pod.status.container_statuses[0].last_state.waiting
        else None,
        "terminated": pod.status.container_statuses[0].last_state.terminated.to_dict()
        if pod.status.container_statuses[0].last_state.terminated
        else None,
    }

    if (
        hasattr(pod.status.container_statuses[0].last_state, "terminated")
        and pod.status.container_statuses[0].last_state.terminated
    ):
        pod.status.container_statuses[0].last_state.terminated.to_dict = lambda: {
            "exitCode": pod.status.container_statuses[0].last_state.terminated.exit_code,
            "reason": pod.status.container_statuses[0].last_state.terminated.reason,
            "startedAt": pod.status.container_statuses[0].last_state.terminated.started_at,
            "finishedAt": pod.status.container_statuses[0].last_state.terminated.finished_at,
        }

    return pod

@pytest.fixture
def create_api_test_nodes():

    def _create_nodes(num_nodes):
        nodes = []

        for i in range(num_nodes):
            nodes.append({
                "metadata": {
                    "name": "node1",
                    "labels": {
                        "chutes/validator": "TEST123",
                        "chutes/external-ip": "192.168.1.100",
                        "nvidia.com/gpu.memory": "16384",
                    },
                    "uid": "node1-uid",
                },
                "status": {
                    "phase": "Ready",
                    "capacity": {"cpu": "8", "memory": "32Gi", "nvidia.com/gpu": "2"},
                },
            })

        return nodes
    
    return _create_nodes

@pytest.fixture
def create_api_test_pods():
    """
    Fixture to create a specified number of pod dictionaries with proper Kubernetes
    camelCase/PascalCase naming convention that are JSON serializable.

    Args:
        num_pods (int): Number of pods to create
        namespace (str, optional): Namespace for the pods. Defaults to "default"
        base_name (str, optional): Base name for the pods. Defaults to "test-pod"
        phase (str, optional): Pod phase. Defaults to "Running"

    Returns:
        list: List of pod dictionaries that are JSON serializable with Kubernetes naming convention
    """

    def _create_pods(num_pods, namespace="chutes", base_name="chute", phase="Running", job=None):
        pods = []

        for i in range(num_pods):
            # Generate unique identifiers
            pod_name = f"{base_name}-{i}"
            pod_uid = str(uuid.uuid4())
            rs_uid = str(uuid.uuid4())
            deployment_uuid = job["metadata"]["labels"]["chutes/deployment-id"] if job else f"deployment-{uuid.uuid4()}"
            container_id = f"containerd://{uuid.uuid4().hex}"

            # Format current time in ISO format for JSON compatibility
            current_time = datetime.now(timezone.utc).isoformat()
            start_time = current_time

            # Base pod template with camelCase/PascalCase keys
            pod = {
                "apiVersion": "v1",
                "kind": "Pod",
                "metadata": {
                    "annotations": {
                        "resource.karmada.io/cached-from-cluster": f"member{random.randint(1, 5)}"
                    },
                    "creationTimestamp": current_time,
                    "deletionTimestamp": None,
                    "deletionGracePeriodSeconds": None,
                    "finalizers": None,
                    "generateName": f"{base_name}-",
                    "generation": None,
                    "labels": {
                        "app": base_name, 
                        "pod-template-hash": "5bf549858c",
                        "chutes/deployment-id": f"{deployment_uuid}"
                    },
                    "name": pod_name,
                    "namespace": namespace,
                    "ownerReferences": [
                        {
                            "apiVersion": "apps/v1",
                            "blockOwnerDeletion": True,
                            "controller": True,
                            "kind": "ReplicaSet",
                            "name": f"{base_name}-5bf549858c",
                            "uid": rs_uid,
                        }
                    ],
                    "resourceVersion": str(random.randint(100, 999)),
                    "uid": pod_uid,
                },
                "spec": {
                    "containers": [
                        {
                            "args": None,
                            "command": None,
                            "env": None,
                            "image": "docker.io/example/app:latest",
                            "imagePullPolicy": "IfNotPresent",
                            "name": "main-container",
                            "ports": [
                                {
                                    "containerPort": 8080,
                                    "hostIP": None,
                                    "hostPort": None,
                                    "name": "http",
                                    "protocol": "TCP",
                                }
                            ],
                            "resources": {"limits": None, "requests": None},
                            "volumeMounts": [
                                {
                                    "mountPath": "/etc/config",
                                    "name": "config-volume",
                                    "readOnly": True,
                                    "subPath": None,
                                }
                            ],
                        }
                    ],
                    "nodeName": f"test-node",
                    "restartPolicy": "Always",
                    "serviceAccount": f"{base_name}-sa",
                    "serviceAccountName": f"{base_name}-sa",
                    "tolerations": [
                        {
                            "effect": "NoExecute",
                            "key": "node.kubernetes.io/not-ready",
                            "operator": "Exists",
                            "tolerationSeconds": 300,
                        }
                    ],
                    "volumes": [
                        {
                            "name": "config-volume",
                            "configMap": {"name": f"{base_name}-config", "defaultMode": 420},
                        }
                    ],
                },
                "status": {
                    "conditions": [
                        {
                            "lastProbeTime": None,
                            "lastTransitionTime": current_time,
                            "message": None,
                            "reason": None,
                            "status": "True",
                            "type": "Initialized",
                        },
                        {
                            "lastProbeTime": None,
                            "lastTransitionTime": current_time,
                            "message": None,
                            "reason": None,
                            "status": "True" if phase == "Running" else "False",
                            "type": "Ready",
                        },
                        {
                            "lastProbeTime": None,
                            "lastTransitionTime": current_time,
                            "message": None,
                            "reason": None,
                            "status": "True" if phase == "Running" else "False",
                            "type": "ContainersReady",
                        },
                        {
                            "lastProbeTime": None,
                            "lastTransitionTime": current_time,
                            "message": None,
                            "reason": None,
                            "status": "True",
                            "type": "PodScheduled",
                        },
                    ],
                    "containerStatuses": [
                        {
                            "containerId": container_id,
                            "image": "docker.io/example/app:latest",
                            "imageID": f"docker.io/example/app@sha256:{uuid.uuid4().hex}",
                            "name": "main-container",
                            "ready": phase == "Running",
                            "restartCount": random.randint(0, 3),
                            "started": phase == "Running",
                            "state": {
                                "running": {"startedAt": current_time}
                                if phase == "Running"
                                else None,
                                "terminated": {
                                    "exitCode": 1,
                                    "reason": "Error",
                                    "startedAt": current_time,
                                    "finishedAt": current_time,
                                }
                                if phase == "Failed"
                                else None,
                                "waiting": {"reason": "ContainerCreating"}
                                if phase == "Pending"
                                else None,
                            },
                            "lastState": {
                                "running": None,
                                "terminated": {
                                    "exitCode": random.choice([0, 1]),
                                    "reason": random.choice(["Completed", "Error", "OOMKilled"]),
                                    "startedAt": current_time,
                                    "finishedAt": current_time,
                                }
                                if random.random() > 0.5
                                else None,
                                "waiting": None,
                            },
                        }
                    ],
                    "hostIP": f"172.26.0.{random.randint(2, 10)}",
                    "phase": phase,
                    "podIP": f"10.14.{random.randint(0, 255)}.{random.randint(1, 254)}",
                    "podIPs": [{"ip": f"10.14.{random.randint(0, 255)}.{random.randint(1, 254)}"}],
                    "qosClass": "BestEffort",
                    "startTime": start_time,
                },
            }

            # Verify JSON serializability
            try:
                json.dumps(pod)
            except TypeError as e:
                raise ValueError(f"Pod is not JSON serializable: {e}")

            pods.append(pod)

        return pods

    return _create_pods


@pytest.fixture
def create_api_test_deployments():
    """
    Create a specified number of test Kubernetes deployments as dictionaries with camel case keys.

    Usage:
        def test_something(test_deployments):
            deployments = test_deployments(3)  # Creates 3 test deployments
    """

    def _generate_deployments(count=1, name="test-app", namespace="chutes"):
        deployments = []

        for i in range(count):
            app_name = f"{name}-{i}"
            current_timestamp = datetime.now(tzutc()).isoformat()
            # Create deployment directly with camelCase keys
            deployment = {
                "apiVersion": "apps/v1",
                "kind": "Deployment",
                "metadata": {
                    "annotations": {
                        "deployment.kubernetes.io/revision": "1",
                        "kubectl.kubernetes.io/last-applied-configuration": f'{{"apiVersion":"apps/v1","kind":"Deployment","metadata":{{"name":"{app_name}","namespace":"default"}}}}',
                    },
                    "creationTimestamp": current_timestamp,
                    "generation": 1,
                    "name": app_name,
                    "namespace": namespace,
                    "resourceVersion": str(1000 + i),
                    "uid": str(uuid.uuid4()),
                    "labels": {
                        "app": app_name,
                        "chutes/deployment-id": f"chute-{app_name}",
                        "chutes/chute-id": f"chute-{uuid.uuid4()}",
                        "chutes/version": "1",
                        "chutes/chute": "true",
                    },
                },
                "spec": {
                    "progressDeadlineSeconds": 600,
                    "replicas": i + 1,
                    "revisionHistoryLimit": 10,
                    "selector": {"matchLabels": {"app": app_name}},
                    "strategy": {
                        "rollingUpdate": {"maxSurge": "25%", "maxUnavailable": "25%"},
                        "type": "RollingUpdate",
                    },
                    "template": {
                        "metadata": {"labels": {"app": app_name}},
                        "spec": {
                            "containers": [
                                {
                                    "image": f"docker.io/test/{app_name}:latest",
                                    "imagePullPolicy": "IfNotPresent",
                                    "name": app_name,
                                    "resources": {},
                                    "terminationMessagePath": "/dev/termination-log",
                                    "terminationMessagePolicy": "File",
                                    "volumeMounts": [
                                        {"mountPath": "/etc/config/", "name": "config-volume"}
                                    ],
                                }
                            ],
                            "dnsPolicy": "ClusterFirst",
                            "nodeSelector": {"kubernetes.io/os": "linux"},
                            "restartPolicy": "Always",
                            "schedulerName": "default-scheduler",
                            "securityContext": {},
                            "serviceAccount": f"{app_name}-service-account",
                            "serviceAccountName": f"{app_name}-service-account",
                            "terminationGracePeriodSeconds": 30,
                            "tolerations": [
                                {
                                    "effect": "NoSchedule",
                                    "key": "node-role.kubernetes.io/control-plane",
                                    "operator": "Equal",
                                }
                            ],
                            "volumes": [
                                {
                                    "configMap": {"defaultMode": 420, "name": f"{app_name}-config"},
                                    "name": "config-volume",
                                }
                            ],
                        },
                    },
                },
                "status": {
                    "availableReplicas": i + 1,
                    "conditions": [
                        {
                            "lastTransitionTime": current_timestamp,
                            "lastUpdateTime": current_timestamp,
                            "message": "Deployment has minimum availability.",
                            "reason": "MinimumReplicasAvailable",
                            "status": "True",
                            "type": "Available",
                        },
                        {
                            "lastTransitionTime": current_timestamp,
                            "lastUpdateTime": current_timestamp,
                            "message": f'ReplicaSet "{app_name}-abc123" has successfully progressed.',
                            "reason": "NewReplicaSetAvailable",
                            "status": "True",
                            "type": "Progressing",
                        },
                    ],
                    "observedGeneration": 1,
                    "readyReplicas": i + 1,
                    "replicas": i + 1,
                    "updatedReplicas": i + 1,
                },
            }

            deployments.append(deployment)

        return deployments

    return _generate_deployments

@pytest.fixture
def create_api_test_jobs():
    """
    Create a specified number of test Kubernetes jobs as dictionaries with camel case keys.

    Usage:
        def test_something(test_jobs):
            jobs = test_jobs(3)  # Creates 3 test jobs
    """

    def _generate_jobs(count=1, name="test-job", namespace="chutes"):
        jobs = []

        for i in range(count):
            app_name = f"{name}-{i}"
            current_timestamp = datetime.now(tzutc()).isoformat()
            # Create job directly with camelCase keys
            job = {
                "apiVersion": "batch/v1",
                "kind": "Job",
                "metadata": {
                    "annotations": {
                        "kubectl.kubernetes.io/last-applied-configuration": f'{{"apiVersion":"batch/v1","kind":"Job","metadata":{{"name":"{app_name}","namespace":"default"}}}}',
                    },
                    "creationTimestamp": current_timestamp,
                    "generation": 1,
                    "name": app_name,
                    "namespace": namespace,
                    "resourceVersion": str(1000 + i),
                    "uid": str(uuid.uuid4()),
                    "labels": {
                        "app": app_name,
                        "chutes/job-id": f"chute-{app_name}",
                        "chutes/chute-id": f"chute-{uuid.uuid4()}",
                        "chutes/version": "1",
                        "chutes/chute": "true",
                        "chutes/deployment-id": f"deployment-{uuid.uuid4()}"
                    },
                },
                "spec": {
                    "activeDeadlineSeconds": 3600,
                    "backoffLimit": 6,
                    "completions": 1,
                    "parallelism": 1,
                    "template": {
                        "metadata": {
                            "labels": {"app": app_name}
                        },
                        "spec": {
                            "nodeName": "test-node",
                            "containers": [
                                {
                                    "image": f"docker.io/test/{app_name}:latest",
                                    "imagePullPolicy": "IfNotPresent",
                                    "name": app_name,
                                    "resources": {},
                                    "terminationMessagePath": "/dev/termination-log",
                                    "terminationMessagePolicy": "File",
                                    "volumeMounts": [
                                        {"mountPath": "/etc/config/", "name": "config-volume"}
                                    ],
                                }
                            ],
                            "dnsPolicy": "ClusterFirst",
                            "nodeSelector": {"kubernetes.io/os": "linux"},
                            "restartPolicy": "Never",
                            "schedulerName": "default-scheduler",
                            "securityContext": {},
                            "serviceAccount": f"{app_name}-service-account",
                            "serviceAccountName": f"{app_name}-service-account",
                            "terminationGracePeriodSeconds": 30,
                            "tolerations": [
                                {
                                    "effect": "NoSchedule",
                                    "key": "node-role.kubernetes.io/control-plane",
                                    "operator": "Equal",
                                }
                            ],
                            "volumes": [
                                {
                                    "configMap": {"defaultMode": 420, "name": f"{app_name}-config"},
                                    "name": "config-volume",
                                }
                            ],
                        },
                    },
                },
                "status": {
                    "active": 1 if i % 3 == 0 else None,  # Some jobs running
                    "succeeded": 1 if i % 3 == 1 else None,  # Some jobs completed
                    "failed": 1 if i % 3 == 2 else None,  # Some jobs failed
                    "conditions": [
                        {
                            "lastProbeTime": current_timestamp,
                            "lastTransitionTime": current_timestamp,
                            "message": "Job completed successfully" if i % 3 == 1 else "Job is running",
                            "reason": "Complete" if i % 3 == 1 else "Running",
                            "status": "True" if i % 3 == 1 else "False",
                            "type": "Complete",
                        }
                    ],
                    "startTime": current_timestamp,
                    "completionTime": current_timestamp if i % 3 == 1 else None,
                },
            }

            jobs.append(job)

        return jobs

    return _generate_jobs