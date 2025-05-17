import json
import os
import sys
from sqlalchemy import (
    create_engine,
)
from sqlalchemy.orm import sessionmaker
import datetime
import random
import uuid

sys.path.insert(0, os.getcwd())

os.environ["MINER_SS58"] = "5E6xfU3oNU7y1a7pQwoc31fmUjwBZ2gKcNCw8EXsdtCQieUQ"
os.environ["MINER_SEED"] = "0xe031170f32b4cda05df2f3cf6bc8d7687b683bbce23d9fa960c0b3fc21641b8a"

validators_json = {
    "supported": [
        {
            "hotkey": "test_validator",
            "registry": "test-registry",
            "api": "http://test-api",
            "socket": "ws://test-socket",
        }
    ]
}
os.environ["VALIDATORS"] = json.dumps(validators_json)

from api.database import Base  # noqa
from api.chute.schemas import Chute  # noqa
from api.deployment.schemas import Deployment  # noqa
from api.gpu.schemas import GPU  # noqa
from api.server.schemas import Server  # noqa


def create_test_data(session, num_servers=3, num_chutes=2, deployments_per_server=2):
    """Create test chutes, servers, GPUs, and deployments"""

    # GPU model types to use
    gpu_models = ["A100", "H100", "RTX4090", "V100", "A6000"]

    # Create chutes first (needed for deployments)
    chutes = []
    for i in range(num_chutes):
        chute_id = f"chute-{uuid.uuid4()}"
        supported_gpus = random.sample(gpu_models, k=random.randint(1, len(gpu_models)))
        gpu_count = random.randint(1, 4)

        chute = Chute(
            chute_id=chute_id,
            validator=f"validator-{i+1}",
            name=f"test-chute-{i+1}",
            image=f"docker-registry.example.com/chutes/chute-{i+1}:latest",
            code=f"github.com/example/chute-{i+1}",
            filename=f"main_{i+1}.py",
            ref_str=f"ref-{uuid.uuid4().hex[:8]}",
            version=f"1.{random.randint(0, 9)}.{random.randint(0, 99)}",
            supported_gpus=supported_gpus,
            gpu_count=gpu_count,
            ban_reason=None,
        )
        session.add(chute)
        chutes.append(chute)

    session.commit()

    # Create servers
    servers = []
    for i in range(num_servers):
        gpu_count = random.randint(2, 8)
        server_id = f"server-{uuid.uuid4()}"
        validator_name = f"validator-{i+1}"

        server = Server(
            server_id=server_id,
            validator=validator_name,
            name=f"test-server-{i+1}",
            ip_address=f"192.168.1.{10+i}",
            verification_port=random.randint(8000, 9000),
            status=random.choice(["active", "maintenance", "offline"]),
            labels={"environment": "test", "region": "us-west", "tier": f"tier-{i+1}"},
            seed=random.randint(1000, 9999),
            gpu_count=gpu_count,
            cpu_per_gpu=random.randint(4, 16),
            memory_per_gpu=random.randint(16, 64),
            hourly_cost=random.uniform(0.5, 5.0),
            locked=random.choice([True, False]),
        )
        session.add(server)
        servers.append(server)

    # Commit to get server IDs
    session.commit()

    # Create GPUs for each server
    for server in servers:
        for j in range(server.gpu_count):
            model = random.choice(gpu_models)
            gpu = GPU(
                gpu_id=f"gpu-{uuid.uuid4()}",
                validator=server.validator,
                server_id=server.server_id,
                device_info={
                    "name": model,
                    "memory": random.choice([16, 24, 32, 40, 80]),
                    "compute_capability": f"{random.randint(7, 9)}.{random.randint(0, 9)}",
                    "driver_version": f"{random.randint(470, 535)}.{random.randint(10, 99)}",
                    "uuid": f"GPU-{uuid.uuid4().hex[:16]}",
                    "index": j,
                    "clock_rate": 10000,
                    "processors": 8,
                },
                model_short_ref=model,
                verified=random.choice([True, False]),
            )
            session.add(gpu)

    session.commit()

    # Create deployments for each server
    for server in servers:
        # Get all available GPUs for this server
        server_gpus = (
            session.query(GPU)
            .filter(GPU.server_id == server.server_id, GPU.deployment_id is None)
            .all()
        )

        for j in range(min(deployments_per_server, len(chutes))):
            chute = chutes[j % len(chutes)]

            # Only create deployment if server has enough GPUs of supported type
            compatible_gpus = [
                gpu for gpu in server_gpus if gpu.model_short_ref in chute.supported_gpus
            ]
            if len(compatible_gpus) < chute.gpu_count:
                continue

            deployment_id = f"deploy-{uuid.uuid4()}"
            deployment = Deployment(
                deployment_id=deployment_id,
                instance_id=f"instance-{uuid.uuid4().hex[:8]}",
                validator=server.validator,
                host=server.ip_address,
                port=random.randint(5000, 7000),
                chute_id=chute.chute_id,
                server_id=server.server_id,
                version=chute.version,
                active=random.choice([True, False]),
                verified_at=datetime.datetime.utcnow()
                - datetime.timedelta(hours=random.randint(1, 48))
                if random.choice([True, False])
                else None,
                stub=False,
            )
            session.add(deployment)

            # Assign the required number of GPUs to this deployment
            gpus_needed = chute.gpu_count
            assigned_gpus = compatible_gpus[:gpus_needed]

            # Remove these GPUs from available list
            for gpu in assigned_gpus:
                server_gpus.remove(gpu)
                gpu.deployment_id = deployment_id
                session.add(gpu)

    # Commit all deployments and GPU assignments
    session.commit()
    print(f"Created {len(servers)} servers")
    print(f"Created {num_chutes} chutes")

    # Count deployments
    deployments = session.query(Deployment).all()
    print(f"Created {len(deployments)} total deployments")


def main():
    # Create a PostgreSQL test database
    # You'll need to update this connection string to your actual database
    engine = create_engine("postgresql://user:password@postgres:5432/chutes", echo=True)

    # Create all tables
    Base.metadata.create_all(engine)

    # Create a session
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        # Create test data
        create_test_data(session)

        # Example queries to verify data was added
        servers = session.query(Server).all()
        print(f"\nServers in database: {len(servers)}")
        for server in servers:
            print(
                f"Server: {server.name}, GPUs: {server.gpu_count}, Deployments: {len(server.deployments)}"
            )
            for deployment in server.deployments:
                gpu_count = len(deployment.gpus)
                print(
                    f"  - {deployment.deployment_id[:8]}... (chute: {deployment.chute.name}, version: {deployment.version}, active: {deployment.active}, GPUs: {gpu_count})"
                )

                # List GPUs assigned to this deployment
                for gpu in deployment.gpus:
                    print(f"    * GPU: {gpu.model_short_ref} ({gpu.gpu_id[:8]}...)")

    finally:
        # Close the session
        session.close()


if __name__ == "__main__":
    main()
