
# Fixtures for commonly used objects
from unittest.mock import MagicMock, patch

import pytest

from api.chute.schemas import Chute
from api.gpu.schemas import GPU
from api.server.schemas import Server

@pytest.fixture
def mock_k8s_core_client():
    with patch("api.k8s.k8s_core_client") as mock_client:
        mock_client.return_value = mock_client
        yield mock_client

@pytest.fixture
def mock_k8s_app_client():
    with patch("api.k8s.k8s_app_client") as mock_client:
        yield mock_client

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
    )
    
    # Add GPUs to the server
    server.gpus = [
        GPU(gpu_id=f"gpu-{i}", server_id="test-server-id", verified=True)
        for i in range(4)
    ]
    
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
        ref_str="test-ref-str"
    )


@pytest.fixture
def mock_watch():
    with patch("api.k8s.watch.Watch") as mock_watch:
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
        "squid-access": "true"
    }
    deployment.metadata.annotations = {
        "deployment.kubernetes.io/revision": "1"
    }
    
    # Spec
    deployment.spec = MagicMock()
    deployment.spec.replicas = 1
    deployment.spec.selector = MagicMock()
    deployment.spec.selector.match_labels = {
        "chutes/deployment-id": "test-123"
    }
    deployment.spec.template = MagicMock()
    deployment.spec.template.metadata = MagicMock()
    deployment.spec.template.metadata.labels = deployment.metadata.labels.copy()
    deployment.spec.template.spec = MagicMock()
    deployment.spec.template.spec.node_selector = {
        "chutes/worker": "true"
    }
    deployment.spec.template.spec.containers = [MagicMock()]
    deployment.spec.template.spec.containers[0].name = "chute"
    deployment.spec.template.spec.containers[0].image = "test-validator.localregistry.chutes.ai:5000/test-image:latest"
    deployment.spec.template.spec.containers[0].resources = MagicMock()
    deployment.spec.template.spec.containers[0].resources.requests = {
        "cpu": "8",
        "memory": "32Gi",
        "nvidia.com/gpu": "2"
    }
    deployment.spec.template.spec.containers[0].resources.limits = {
        "cpu": "8",
        "memory": "32Gi",
        "nvidia.com/gpu": "2"
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
        MagicMock(type="Progressing", status="True")
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
        "pod-template-hash": "69d74d8dcf"
    }
    pod.metadata.owner_references = [
        MagicMock(
            api_version="apps/v1",
            kind="ReplicaSet",
            name="chute-test-123-69d74d8dcf",
            uid="rs-11112222-3333-4444-5555-666677778888"
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
        "nvidia.com/gpu": "2"
    }
    pod.spec.containers[0].resources.limits = {
        "cpu": "8",
        "memory": "32Gi",
        "nvidia.com/gpu": "2"
    }
    pod.spec.volumes = [
        MagicMock(name="code"),
        MagicMock(name="cache"),
        MagicMock(name="tmp"),
        MagicMock(name="shm")
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
        MagicMock(type="PodScheduled", status="True")
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
    pod.status.container_statuses[0].image = "test-validator.localregistry.chutes.ai:5000/test-image:latest"
    pod.status.container_statuses[0].image_id = "docker-pullable://test-validator.localregistry.chutes.ai:5000/test-image@sha256:1234567890abcdef"
    pod.status.container_statuses[0].container_id = "containerd://1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"
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
    
    def set_error(reason="CrashLoopBackOff", message="Back-off restarting failed container", exit_code=1):
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
        "running": pod.status.container_statuses[0].state.running.to_dict() if pod.status.container_statuses[0].state.running else None,
        "waiting": pod.status.container_statuses[0].state.waiting.to_dict() if pod.status.container_statuses[0].state.waiting else None,
        "terminated": pod.status.container_statuses[0].state.terminated.to_dict() if pod.status.container_statuses[0].state.terminated else None
    }
    
    if pod.status.container_statuses[0].state.running:
        pod.status.container_statuses[0].state.running.to_dict = lambda: {
            "startedAt": pod.status.container_statuses[0].state.running.started_at
        }
    
    # These methods will be created if the states are set via the helper methods
    if hasattr(pod.status.container_statuses[0].state, 'waiting') and pod.status.container_statuses[0].state.waiting:
        pod.status.container_statuses[0].state.waiting.to_dict = lambda: {
            "reason": pod.status.container_statuses[0].state.waiting.reason,
            "message": pod.status.container_statuses[0].state.waiting.message
        }
    
    # Same for last_state
    pod.status.container_statuses[0].last_state.to_dict = lambda: {
        "running": pod.status.container_statuses[0].last_state.running.to_dict() if pod.status.container_statuses[0].last_state.running else None,
        "waiting": pod.status.container_statuses[0].last_state.waiting.to_dict() if pod.status.container_statuses[0].last_state.waiting else None,
        "terminated": pod.status.container_statuses[0].last_state.terminated.to_dict() if pod.status.container_statuses[0].last_state.terminated else None
    }
    
    if hasattr(pod.status.container_statuses[0].last_state, 'terminated') and pod.status.container_statuses[0].last_state.terminated:
        pod.status.container_statuses[0].last_state.terminated.to_dict = lambda: {
            "exitCode": pod.status.container_statuses[0].last_state.terminated.exit_code,
            "reason": pod.status.container_statuses[0].last_state.terminated.reason,
            "startedAt": pod.status.container_statuses[0].last_state.terminated.started_at,
            "finishedAt": pod.status.container_statuses[0].last_state.terminated.finished_at
        }
    
    return pod