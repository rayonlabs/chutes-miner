"""
Gepetto - coordinate all the things.
"""

import aiohttp
import asyncio
import orjson as json
import traceback
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from loguru import logger
from typing import Dict, Any, Optional
from sqlalchemy import select, func, case, text, or_, update
from sqlalchemy.orm import selectinload
from prometheus_api_client import PrometheusConnect
from api.config import settings, validator_by_hotkey, Validator
from api.redis_pubsub import RedisListener
from api.auth import sign_request
from api.database import get_session, engine, Base
from api.chute.schemas import Chute
from api.server.schemas import Server
from api.gpu.schemas import GPU
from api.deployment.schemas import Deployment
from api.exceptions import DeploymentFailure
import api.k8s as k8s


class Gepetto:
    def __init__(self):
        """
        Constructor.
        """
        self.pubsub = RedisListener()
        self.remote_chutes = {validator.hotkey: {} for validator in settings.validators}
        self.remote_images = {validator.hotkey: {} for validator in settings.validators}
        self.remote_instances = {validator.hotkey: {} for validator in settings.validators}
        self.remote_nodes = {validator.hotkey: {} for validator in settings.validators}
        self.remote_metrics = {validator.hotkey: {} for validator in settings.validators}
        self._scale_lock = asyncio.Lock()
        self.setup_handlers()

    def setup_handlers(self):
        """
        Configure the various event listeners/handlers.
        """
        self.pubsub.on_event("gpu_verified")(self.gpu_verified)
        self.pubsub.on_event("server_deleted")(self.server_deleted)
        self.pubsub.on_event("gpu_deleted")(self.gpu_deleted)
        self.pubsub.on_event("instance_verified")(self.instance_verified)
        self.pubsub.on_event("instance_deleted")(self.instance_deleted)
        self.pubsub.on_event("rolling_update")(self.rolling_update)
        self.pubsub.on_event("chute_deleted")(self.chute_deleted)
        self.pubsub.on_event("chute_created")(self.chute_created)
        self.pubsub.on_event("chute_updated")(self.chute_updated)
        self.pubsub.on_event("bounty_change")(self.bounty_changed)
        self.pubsub.on_event("image_deleted")(self.image_deleted)
        self.pubsub.on_event("image_created")(self.image_created)

    async def run(self):
        """
        Main loop.
        """
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        await self.reconcile()
        asyncio.create_task(self.activator())
        asyncio.create_task(self.autoscaler())
        asyncio.create_task(self.reconciler())
        await self.pubsub.start()

    @staticmethod
    async def _remote_refresh_objects(
        pointer: Dict[str, Any],
        hotkey: str,
        url: str,
        id_key: str,
    ):
        """
        Refresh images/chutes from validator(s).
        """
        async with aiohttp.ClientSession(raise_for_status=True) as session:
            headers, _ = sign_request(purpose="miner")
            updated_items = {}
            async with session.get(url, headers=headers) as resp:
                async for content_enc in resp.content:
                    content = content_enc.decode()
                    if content.startswith("data: "):
                        data = json.loads(content[6:])
                        updated_items[data[id_key]] = data
            if updated_items:
                pointer[hotkey] = updated_items

    async def remote_refresh_all(self):
        """
        Refresh chutes from the validators.
        """
        for validator in settings.validators:
            for clazz, id_field in (
                ("chutes", "chute_id"),
                ("images", "image_id"),
                ("nodes", "uuid"),
                ("instances", "instance_id"),
                ("metrics", "chute_id"),
            ):
                logger.debug(f"Refreshing {clazz} from {validator.hotkey}...")
                await self._remote_refresh_objects(
                    getattr(self, f"remote_{clazz}"),
                    validator.hotkey,
                    f"{validator.api}/miner/{clazz}/",
                    id_field,
                )

    @staticmethod
    async def load_chute(chute_id: str, version: str, validator: str):
        """
        Helper to load a chute from the local database.
        """
        async with get_session() as session:
            return (
                await session.execute(
                    select(Chute)
                    .where(Chute.chute_id == chute_id)
                    .where(Chute.version == version)
                    .where(Chute.validator == validator)
                )
            ).scalar_one_or_none()

    @staticmethod
    async def count_deployments(chute_id: str, version: str, validator: str):
        """
        Helper to get the number of deployments for a chute.
        """
        async with get_session() as session:
            return (
                await session.execute(
                    select(func.count())
                    .select_from(Deployment)
                    .where(Deployment.chute_id == chute_id)
                    .where(Deployment.version == version)
                    .where(Deployment.validator == validator)
                )
            ).scalar()

    @staticmethod
    async def get_chute(chute_id: str, validator: str) -> Optional[Chute]:
        """
        Load a chute by ID.
        """
        async with get_session() as session:
            return (
                (
                    await session.execute(
                        select(Chute).where(
                            Chute.chute_id == chute_id, Chute.validator == validator
                        )
                    )
                )
                .unique()
                .scalar_one_or_none()
            )

    async def announce_deployment(self, deployment: Deployment):
        """
        Tell a validator that we're creating a deployment.
        """
        if (vali := validator_by_hotkey(deployment.validator)) is None:
            logger.warning(f"No validator for deployment: {deployment.deployment_id}")
            return
        body = {
            "node_ids": [gpu.gpu_id for gpu in deployment.gpus],
            "host": deployment.host,
            "port": deployment.port,
        }
        try:
            async with aiohttp.ClientSession(raise_for_status=False) as session:
                headers, payload_string = sign_request(payload=body)
                async with session.post(
                    f"{vali.api}/instances/{deployment.chute_id}/",
                    headers=headers,
                    data=payload_string,
                ) as resp:
                    if resp.status >= 300:
                        logger.error(
                            f"Error announcing deployment to validator:\n{await resp.text()}"
                        )
                    resp.raise_for_status()
                    instance = await resp.json()

                    # Track the instance ID.
                    async with get_session() as session:
                        await session.execute(
                            update(Deployment)
                            .where(Deployment.deployment_id == deployment.deployment_id)
                            .values({"instance_id": instance["instance_id"]})
                        )
                        await session.commit()
                    logger.success(f"Successfully advertised instance: {instance['instance_id']}")
        except Exception as exc:
            logger.warning(f"Error announcing deployment: {exc}\n{traceback.format_exc()}")
            raise DeploymentFailure(
                f"Failed to announce deployment {deployment.deployment_id}: {exc=}"
            )

    async def activate(self, deployment: Deployment):
        """
        Tell a validator that a deployment is active/ready.
        """
        if (vali := validator_by_hotkey(deployment.validator)) is None:
            logger.warning(f"No validator for deployment: {deployment.deployment_id}")
            return
        body = {"active": True}
        async with aiohttp.ClientSession(raise_for_status=False) as session:
            headers, payload_string = sign_request(payload=body)
            async with session.patch(
                f"{vali.api}/instances/{deployment.chute_id}/{deployment.instance_id}",
                headers=headers,
                data=payload_string,
            ) as resp:
                if resp.status >= 300:
                    logger.error(f"Error activating deployment:\n{await resp.text()}")
                resp.raise_for_status()
                data = await resp.json()
                async with get_session() as session:
                    deployment = (
                        (
                            await session.execute(
                                select(Deployment).where(
                                    Deployment.deployment_id == deployment.deployment_id
                                )
                            )
                        )
                        .unique()
                        .scalar_one_or_none()
                    )
                    if deployment:
                        deployment.active = True
                        if data.get("verified"):
                            deployment.verified_at = func.now()
                        await session.commit()
                logger.success(f"Successfully activated {deployment.instance_id=}")

    async def activator(self):
        """
        Loop to mark all deployments ready in the validator when they are ready in k8s.
        """
        while True:
            try:
                query = select(Deployment).where(
                    or_(
                        Deployment.active.is_(False),
                        Deployment.verified_at.is_(None),
                    ),
                    Deployment.stub.is_(False),
                    Deployment.instance_id.is_not(None),
                )
                async with get_session() as session:
                    deployments = (await session.execute(query)).unique().scalars()
                if not deployments:
                    await asyncio.sleep(5)
                    continue

                # For each deployment, check if it's ready to go in kubernetes.
                for deployment in deployments:
                    k8s_deployment = await k8s.get_deployment(deployment.deployment_id)
                    if not k8s_deployment:
                        logger.warning("NO K8s!")
                    if k8s_deployment.get("ready"):
                        await self.activate(deployment)
                await asyncio.sleep(5)
            except Exception as exc:
                logger.error(f"Error performing announcement loop: {exc}")
                await asyncio.sleep(5)

    async def _autoscale(self):
        """
        Autoscale chutes, based on metrics and server availability.
        """
        for validator in settings.validators:
            await self._remote_refresh_objects(
                self.remote_metrics, validator.hotkey, f"{validator.api}/miner/metrics/", "chute_id"
            )

        # Load chute utilization to see if it can scale.
        scalable = {}
        for validator in settings.validators:
            scalable[validator.hotkey] = {}
            async with aiohttp.ClientSession() as session:
                try:
                    async with session.get(f"{validator.api}/chutes/utilization") as resp:
                        for item in await resp.json():
                            if item.get("scalable") is False:
                                scalable[validator.hotkey][item["chute_id"]] = False
                                logger.warning(
                                    f"Chute {item['chute_id']} is capped due to utilization: {item}"
                                )
                            if item.get("update_in_progress") is True:
                                scalable[validator.hotkey][item["chute_id"]] = False
                                logger.warning(
                                    f"Chute {item['chute_id']} is updating, cannot scale now: {item}"
                                )
                except Exception as exc:
                    logger.error(f"Failed to fetch chute utilization from {validator=}: {exc}")

        # Count the number of deployments for each chute
        chute_values = []
        for validator, chutes in self.remote_chutes.items():
            for chute_id, chute_info in chutes.items():
                try:
                    chute_name = chute_info.get("name")
                    chute = await self.load_chute(chute_id, chute_info["version"], validator)
                    if not chute:
                        continue
                    if scalable.get(validator, {}).get(chute_id) not in (None, True):
                        continue

                    # Count how many deployments we already have.
                    local_count = await self.count_deployments(
                        chute_id, chute_info["version"], validator
                    )
                    if local_count >= 3:
                        logger.info(f"Already have max instances of {chute_id=} {chute_name}")
                        continue

                    # If there are no metrics, it means the chute is not being actively used, so don't scale.
                    metrics = self.remote_metrics.get(validator, {}).get(chute_id, {})
                    if not metrics:
                        logger.info(
                            f"No metrics for {chute_id=} {chute_name}, scaling would be unproductive..."
                        )
                        continue

                    # If we have all deployments already (no other miner has this) then no need to scale.
                    total_count = metrics["instance_count"]
                    if local_count and local_count >= total_count:
                        logger.info(
                            f"We have all deployments for {chute_id=} {chute_name}, scaling would be unproductive..."
                        )
                        continue

                    # Calculate potential gain from a new deployment.
                    potential_gain = (
                        metrics["total_usage_usd"]
                        if not total_count
                        else metrics["total_usage_usd"] / (total_count + 1)
                    )

                    # See if we have a server that could even handle it.
                    potential_server = await self.optimal_scale_up_server(chute)
                    if not potential_server:
                        logger.info(f"No viable server to scale {chute_id=} {chute_name}")
                        continue

                    # Calculate value ratio
                    chute_value = potential_gain / (potential_server.hourly_cost * chute.gpu_count)
                    logger.info(
                        f"Estimated {potential_gain=} for name={chute_name} "
                        f"chute_id={chute_info['chute_id']} on {validator=}, "
                        f"optimal server hourly cost={potential_server.hourly_cost} "
                        f"on server {potential_server.name}, {chute_value=} "
                        f"{local_count=} {total_count=}"
                    )
                    chute_values.append((validator, chute_id, chute_value))

                except Exception as e:
                    logger.error(f"Error processing chute {chute_id}: {e}")
                    continue

        if not chute_values:
            logger.info("No benefit in scaling, or no ability to do so...")
            return

        # Sort by value and attempt to deploy the highest value chute
        chute_values.sort(key=lambda x: x[2], reverse=True)
        best_validator, best_chute_id, best_value = chute_values[0]
        if (
            chute := await self.load_chute(
                best_chute_id,
                self.remote_chutes[best_validator][best_chute_id]["version"],
                best_validator,
            )
        ) is not None:
            current_count = await self.count_deployments(
                best_chute_id, chute.version, best_validator
            )
            logger.info(f"Scaling up {best_chute_id} for validator {best_validator}")
            await self.scale_chute(chute, current_count + 1, preempt=False)

    async def autoscaler(self):
        """
        Main autoscaling loop.
        """
        while True:
            try:
                await self._autoscale()
            except Exception as exc:
                logger.error(
                    f"Unexpected error in autoscaling loop: {exc}\n{traceback.format_exc()}"
                )
            await asyncio.sleep(15)

    @staticmethod
    async def purge_validator_instance(vali: Validator, chute_id: str, instance_id: str):
        try:
            async with aiohttp.ClientSession() as session:
                headers, _ = sign_request(purpose="instances")
                async with session.delete(
                    f"{vali.api}/instances/{chute_id}/{instance_id}", headers=headers
                ) as resp:
                    logger.debug(await resp.text())
                    if resp.status not in (200, 404):
                        raise Exception(
                            f"status_code={resp.status}, response text: {await resp.text()}"
                        )
                    elif resp.status == 200:
                        logger.info(f"Deleted instance from validator {vali.hotkey}")
                    else:
                        logger.info(f"{instance_id=} already purged from {vali.hotkey}")
        except Exception as exc:
            logger.warning(f"Error purging {instance_id=} from {vali.hotkey=}: {exc}")

    async def undeploy(self, deployment_id: str):
        """
        Delete a deployment.
        """
        logger.info(f"Removing all traces of deployment: {deployment_id}")

        # Clean up the database.
        instance_id = None
        chute_id = None
        validator_hotkey = None
        async with get_session() as session:
            deployment = (
                (
                    await session.execute(
                        select(Deployment).where(Deployment.deployment_id == deployment_id)
                    )
                )
                .unique()
                .scalar_one_or_none()
            )
            if deployment:
                instance_id = deployment.instance_id
                chute_id = deployment.chute_id
                validator_hotkey = deployment.validator
                await session.delete(deployment)
                await session.commit()

        # Clean up the validator's instance record.
        if instance_id:
            if (vali := validator_by_hotkey(validator_hotkey)) is not None:
                await self.purge_validator_instance(vali, chute_id, instance_id)

        # Purge in k8s if still there.
        await k8s.undeploy(deployment_id)
        logger.success(f"Removed {deployment_id=}")

    async def gpu_verified(self, event_data):
        """
        Validator has finished verifying a GPU, so it is ready for use.
        """
        logger.info(f"Received gpu_verified event: {event_data}")
        async with get_session() as session:
            await session.execute(
                update(GPU)
                .where(GPU.server_id == event_data.get("gpu_id"))
                .values({"verified": True})
            )
            await session.commit()
        # Nothing to do here really, the autoscaler should take care of it, but feel free to change...

    async def instance_verified(self, event_data):
        """
        Validator has finished verifying an instance/deployment, so it should start receiving requests.
        """
        logger.info(f"Received instance_verified event: {event_data}")
        async with get_session() as session:
            await session.execute(
                update(Deployment)
                .where(Deployment.instance_id == event_data.get("instance_id"))
                .values({"verified_at": func.now()})
            )
        # Nothing to do here really, it should just start receiving traffic.

    async def bounty_changed(self, event_data):
        """
        Bounty has changed for a chute.
        """
        logger.info(f"Received bounty_change event: {event_data}")

        # Check if we have this thing deployed already (or in progress).
        chute = None
        async with get_session() as session:
            deployment = (
                (
                    await session.execute(
                        select(Deployment).where(Deployment.chute_id == event_data["chute_id"])
                    )
                )
                .unique()
                .scalar_one_or_none()
            )
            if deployment:
                logger.info(
                    f"Ignoring bounty event, already have a deployment pending: {deployment.deployment_id}"
                )
                return
            chute = await self.get_chute(event_data["chute_id"], event_data["validator"])
        if chute:
            logger.info(f"Attempting to claim the bounty: {event_data}")
            await self.scale_chute(chute, 1, preempt=True)

    @staticmethod
    async def remove_gpu_from_validator(validator: Validator, gpu_id: str):
        """
        Purge a GPU from validator inventory.
        """
        try:
            async with aiohttp.ClientSession(raise_for_status=True) as http_session:
                headers, _ = sign_request(purpose="nodes")
                async with http_session.delete(
                    f"{validator.api}/nodes/{gpu_id}", headers=headers
                ) as resp:
                    logger.success(
                        f"Successfully purged {gpu_id=} from validator={validator.hotkey}: {await resp.json()}"
                    )
        except Exception as exc:
            logger.error(f"Error purging {gpu_id=} from validator={validator.hotkey}: {exc}")

    async def gpu_deleted(self, event_data):
        """
        GPU no longer exists in validator inventory for some reason.

        MINERS: This shouldn't really happen, unless the validator purges it's database
                or some such other rare event.  You may want to configure alerts or something
                in this code block just in case.
        """
        gpu_id = event_data["gpu_id"]
        logger.info(f"Received gpu_deleted event for {gpu_id=}")
        async with get_session() as session:
            gpu = (
                (await session.execute(select(GPU).where(GPU.gpu_id == gpu_id)))
                .unique()
                .scalar_one_or_none()
            )
            if gpu:
                if gpu.deployment:
                    await self.undeploy(gpu.deployment_id)
                validator_hotkey = gpu.validator
                if (validator := validator_by_hotkey(validator_hotkey)) is not None:
                    await self.remove_gpu_from_validator(validator, gpu_id)
                await session.delete(gpu)
                await session.commit()
        logger.info(f"Finished processing gpu_deleted event for {gpu_id=}")

    async def instance_deleted(self, event_data: Dict[str, Any]):
        """
        An instance was removed validator side, likely meaning there were too
        many consecutive failures in inference.
        """
        instance_id = event_data["instance_id"]
        logger.info(f"Received instance_deleted event for {instance_id=}")
        async with get_session() as session:
            deployment = (
                (
                    await session.execute(
                        select(Deployment).where(Deployment.instance_id == instance_id)
                    )
                )
                .unique()
                .scalar_one_or_none()
            )
        if deployment:
            await self.undeploy(deployment.deployment_id)
        logger.info(f"Finished processing instance_deleted event for {instance_id=}")

    async def server_deleted(self, event_data: Dict[str, Any]):
        """
        An entire kubernetes node was removed from your inventory.

        MINERS: This will happen when you remove a node intentionally, but otherwise
                should not really happen.  Also want to monitor this situation I think.
        """
        server_id = event_data["server_id"]
        logger.info(f"Received server_deleted event {server_id=}")
        async with get_session() as session:
            server = (
                (await session.execute(select(Server).where(Server.server_id == server_id)))
                .unique()
                .scalar_one_or_none()
            )
            if server:
                await asyncio.gather(
                    *[self.gpu_deleted({"gpu_id": gpu.gpu_id}) for gpu in server.gpus]
                )
                await session.refresh(server)
                await session.delete(server)
                await session.commit()
        logger.info(f"Finished processing server_deleted event for {server_id=}")

    async def image_deleted(self, event_data: Dict[str, Any]):
        """
        An image was deleted (should clean up maybe?)
        """
        logger.info(f"Image deleted, but I'm lazy and will let k8s clean up: {event_data}")

    async def image_created(self, event_data: Dict[str, Any]):
        """
        An image was created, we could be extra eager and pull the image onto each GPU node so it's hot faster.
        """
        logger.info(
            f"Image created, but I'm going to lazy load the image when chutes are created: {event_data}"
        )

    async def chute_deleted(self, event_data: Dict[str, Any]):
        """
        A chute (or specific version of a chute) was removed from validator inventory.
        """
        chute_id = event_data["chute_id"]
        version = event_data["version"]
        validator = event_data["validator"]
        logger.info(f"Received chute_deleted event for {chute_id=} {version=}")
        async with get_session() as session:
            chute = (
                await session.execute(
                    select(Chute)
                    .where(Chute.chute_id == chute_id)
                    .where(Chute.version == version)
                    .where(Chute.validator == validator)
                    .options(selectinload(Chute.deployments))
                )
            ).scalar_one_or_none()
            if chute:
                if chute.deployments:
                    await asyncio.gather(
                        *[
                            self.undeploy(deployment.deployment_id)
                            for deployment in chute.deployments
                        ]
                    )
                await session.delete(chute)
                await session.commit()
        await k8s.delete_code(chute_id, version)

    async def chute_created(self, event_data: Dict[str, Any], desired_count: int = 1):
        """
        A brand new chute was added to validator inventory.

        MINERS: This is a critical optimization path. A chute being created
                does not necessarily mean inference will be requested. The
                base mining code here *will* deploy the chute however, given
                sufficient resources are available.
        """
        chute_id = event_data["chute_id"]
        version = event_data["version"]
        validator_hotkey = event_data["validator"]
        logger.info(f"Received chute_created event for {chute_id=} {version=}")
        if (validator := validator_by_hotkey(validator_hotkey)) is None:
            logger.warning(f"Validator not found: {validator_hotkey}")
            return

        # Already in inventory?
        if (chute := await self.load_chute(chute_id, version, validator_hotkey)) is not None:
            logger.info(f"Chute {chute_id=} {version=} is already tracked in inventory?")
            return

        # Load the chute details, preferably from the local cache.
        chute_dict = None
        try:
            async with aiohttp.ClientSession(raise_for_status=True) as session:
                headers, _ = sign_request(purpose="miner")
                async with session.get(
                    f"{validator.api}/miner/chutes/{chute_id}/{version}", headers=headers
                ) as resp:
                    chute_dict = await resp.json()
        except Exception:
            logger.error(f"Error loading remote chute data: {chute_id=} {version=}")
            return

        # Track in inventory.
        async with get_session() as session:
            chute = Chute(
                chute_id=chute_id,
                validator=validator.hotkey,
                name=chute_dict["name"],
                image=chute_dict["image"],
                code=chute_dict["code"],
                filename=chute_dict["filename"],
                ref_str=chute_dict["ref_str"],
                version=chute_dict["version"],
                supported_gpus=chute_dict["supported_gpus"],
                gpu_count=chute_dict["node_selector"]["gpu_count"],
                ban_reason=None,
            )
            session.add(chute)
            await session.commit()
            await session.refresh(chute)

        await k8s.create_code_config_map(chute)

        # This should never be anything other than 0, but just in case...
        current_count = await self.count_deployments(chute.chute_id, chute.version, chute.validator)
        if not current_count:
            await self.scale_chute(chute, desired_count=desired_count, preempt=False)

    async def rolling_update(self, event_data: Dict[str, Any]):
        """
        A rolling update event, meaning we need to re-create a single instance.
        """
        chute_id = event_data["chute_id"]
        version = event_data["new_version"]
        validator_hotkey = event_data["validator"]
        instance_id = event_data["instance_id"]
        logger.info(f"Received rolling update event for {chute_id=} {version=} {instance_id=}")

        if (validator := validator_by_hotkey(validator_hotkey)) is None:
            logger.warning(f"Validator not found: {validator_hotkey}")
            return

        # Remove the instance/deployment.
        server_id = None
        async with get_session() as session:
            deployment = (
                (
                    await session.execute(
                        select(Deployment).where(Deployment.instance_id == instance_id)
                    )
                )
                .unique()
                .scalar_one_or_none()
            )
            if deployment:
                server_id = deployment.server.server_id
                await self.undeploy(deployment.deployment_id)
            deployment = None

        # Make sure the local chute is updated.
        if (chute := await self.load_chute(chute_id, version, validator_hotkey)) is None:
            chute_dict = None
            try:
                async with aiohttp.ClientSession(raise_for_status=True) as session:
                    headers, _ = sign_request(purpose="miner")
                    async with session.get(
                        f"{validator.api}/miner/chutes/{chute_id}/{version}", headers=headers
                    ) as resp:
                        chute_dict = await resp.json()
            except Exception:
                logger.error(f"Error loading remote chute data: {chute_id=} {version=}")
                return

            async with get_session() as db:
                chute = (
                    (await db.execute(select(Chute).where(Chute.chute_id == chute_id)))
                    .unique()
                    .scalar_one_or_none()
                )
                if chute:
                    for key in (
                        "image",
                        "code",
                        "filename",
                        "ref_str",
                        "version",
                        "supported_gpus",
                    ):
                        setattr(chute, key, chute_dict.get(key))
                    chute.gpu_count = chute_dict["node_selector"]["gpu_count"]
                else:
                    chute = Chute(
                        chute_id=chute_id,
                        validator=validator.hotkey,
                        name=chute_dict["name"],
                        image=chute_dict["image"],
                        code=chute_dict["code"],
                        filename=chute_dict["filename"],
                        ref_str=chute_dict["ref_str"],
                        version=chute_dict["version"],
                        supported_gpus=chute_dict["supported_gpus"],
                        gpu_count=chute_dict["node_selector"]["gpu_count"],
                        ban_reason=None,
                    )
                    db.add(chute)
                await db.commit()
                await db.refresh(chute)
                await k8s.create_code_config_map(chute)

        # Deploy the new version.
        if server_id:
            logger.info(f"Attempting to deploy {chute.chute_id=} on {server_id=}")
            deployment = None
            try:
                deployment, k8s_dep, k8s_svc = await k8s.deploy_chute(chute.chute_id, server_id)
                logger.success(
                    f"Successfully updated {chute_id=} to {version=} on {server_id=}: {deployment.deployment_id=}"
                )
                await self.announce_deployment(deployment)
            except DeploymentFailure as exc:
                logger.error(
                    f"Unhandled error attempting to deploy {chute.chute_id=} on {server_id=}: {exc}\n{traceback.format_exc()}"
                )
                if deployment:
                    await self.undeploy(deployment.deployment_id)
                return

    async def chute_updated(self, event_data: Dict[str, Any]):
        """
        A new version of a chute was published, meaning we need to replace the existing
        deployments with the updated versions.
        """
        chute_id = event_data["chute_id"]
        version = event_data["version"]
        old_version = event_data.get("old_version")
        validator_hotkey = event_data["validator"]
        logger.info(f"Received chute_updated event for {chute_id=} {version=}")
        current_count = 0
        if old_version:
            current_count = await self.count_deployments(chute_id, version, validator_hotkey)
            await self.chute_deleted(
                {"chute_id": chute_id, "version": old_version, "validator": validator_hotkey}
            )
        await self.chute_created(event_data, desired_count=current_count or 1)

    @staticmethod
    async def optimal_scale_down_deployment(chute: Chute) -> Optional[Deployment]:
        """
        Default strategy for scaling down chutes is to find a deployment based on
        server cost and what will be the server's GPU availability after removal.
        """
        gpu_counts = (
            select(
                Server.server_id,
                func.count(GPU.gpu_id).label("total_gpus"),
                func.sum(case((GPU.deployment_id != None, 1), else_=0)).label("used_gpus"),  # noqa
            )
            .select_from(Server)
            .join(GPU)
            .group_by(Server.server_id)
            .subquery()
        )
        query = (
            select(
                Deployment,
                (Server.hourly_cost * (gpu_counts.c.used_gpus / gpu_counts.c.total_gpus)).label(
                    "removal_score"
                ),
            )
            .select_from(Deployment)
            .join(GPU)
            .join(Server)
            .join(gpu_counts, Server.server_id == gpu_counts.c.server_id)
            .where(Server.locked.is_(False))
            .where(Deployment.chute_id == chute.chute_id)
            .where(Deployment.created_at <= func.now() - timedelta(minutes=5))
            .order_by(text("removal_score DESC"))
            .limit(1)
        )
        async with get_session() as session:
            return (await session.execute(query)).unique().scalar_one_or_none()

    @staticmethod
    async def optimal_scale_up_server(chute: Chute) -> Optional[Server]:
        """
        Find the optimal server for scaling up a chute deployment.
        """
        if chute.ban_reason:
            logger.warning(f"Will not scale up banned chute {chute.chute_id=}: {chute.ban_reason=}")
            return None
        supported_gpus = list(chute.supported_gpus)
        if "h200" in supported_gpus and set(supported_gpus) - set(["h200"]):
            supported_gpus = list(set(supported_gpus) - set(["h200"]))
        total_gpus_per_server = (
            select(Server.server_id, func.count(GPU.gpu_id).label("total_gpus"))
            .select_from(Server)
            .join(GPU, Server.server_id == GPU.server_id)
            .where(GPU.model_short_ref.in_(supported_gpus), GPU.verified.is_(True))
            .group_by(Server.server_id)
            .subquery()
        )
        used_gpus_per_server = (
            select(Server.server_id, func.count(GPU.gpu_id).label("used_gpus"))
            .select_from(Server)
            .join(GPU, Server.server_id == GPU.server_id)
            .where(GPU.verified.is_(True), GPU.deployment_id.isnot(None))
            .group_by(Server.server_id)
            .subquery()
        )
        query = (
            select(
                Server,
                total_gpus_per_server.c.total_gpus,
                func.coalesce(used_gpus_per_server.c.used_gpus, 0).label("used_gpus"),
                (
                    total_gpus_per_server.c.total_gpus
                    - func.coalesce(used_gpus_per_server.c.used_gpus, 0)
                ).label("free_gpus"),
            )
            .select_from(Server)
            .join(total_gpus_per_server, Server.server_id == total_gpus_per_server.c.server_id)
            .outerjoin(used_gpus_per_server, Server.server_id == used_gpus_per_server.c.server_id)
            .join(GPU, Server.server_id == GPU.server_id)
            .where(
                GPU.model_short_ref.in_(supported_gpus),
                GPU.verified.is_(True),
                (
                    total_gpus_per_server.c.total_gpus
                    - func.coalesce(used_gpus_per_server.c.used_gpus, 0)
                    >= chute.gpu_count
                ),
                Server.locked.is_(False),
            )
            .order_by(Server.hourly_cost.asc(), text("free_gpus ASC"))
            .limit(1)
        )
        async with get_session() as session:
            result = await session.execute(query)
            row = result.first()
            return row.Server if row else None

    async def preempting_deploy(self, chute: Chute):
        """
        Force deploy a chute by preempting other deployments (assuming a server exists that can be used).
        """
        if chute.ban_reason:
            logger.warning(
                f"Refusing to perform a preempting deploy of banned chute {chute.chute_id=}: {chute.ban_reason=}"
            )
            return

        supported_gpus = list(chute.supported_gpus)
        if "h200" in supported_gpus and set(supported_gpus) - set(["h200"]):
            supported_gpus = list(set(supported_gpus) - set(["h200"]))
        # Get the prometheus data for staleness check
        prom = PrometheusConnect(url=settings.prometheus_url)
        last_invocations = {}
        try:
            result = prom.custom_query("max by (chute_id) (invocation_last_timestamp)")
            for metric in result:
                chute_id = metric["metric"]["chute_id"]
                timestamp = datetime.fromtimestamp(float(metric["value"][1]))
                last_invocations[chute_id] = timestamp.replace(tzinfo=None)
        except Exception as e:
            logger.error(f"Failed to fetch prometheus metrics: {e}")
            pass

        # Calculate value metrics for each chute per validator
        chute_values = {}
        for chute_id, metric in self.remote_metrics.get(chute.validator, {}).items():
            instance_count = metric["instance_count"]
            value_per_instance = (
                0 if not instance_count else metric["total_usage_usd"] / instance_count
            )
            chute_values[chute_id] = value_per_instance

        # Find all servers that support this chute, sorted by cheapest & most already free GPUs.
        total_gpus_per_server = (
            select(Server.server_id, func.count(GPU.gpu_id).label("total_gpus"))
            .select_from(Server)
            .join(GPU, Server.server_id == GPU.server_id)
            .where(GPU.model_short_ref.in_(supported_gpus), GPU.verified.is_(True))
            .group_by(Server.server_id)
            .subquery()
        )
        used_gpus_per_server = (
            select(Server.server_id, func.count(GPU.gpu_id).label("used_gpus"))
            .select_from(Server)
            .join(GPU, Server.server_id == GPU.server_id)
            .where(GPU.verified.is_(True), GPU.deployment_id.isnot(None))
            .group_by(Server.server_id)
            .subquery()
        )
        query = (
            select(
                Server,
                total_gpus_per_server.c.total_gpus,
                func.coalesce(used_gpus_per_server.c.used_gpus, 0).label("used_gpus"),
                (
                    total_gpus_per_server.c.total_gpus
                    - func.coalesce(used_gpus_per_server.c.used_gpus, 0)
                ).label("free_gpus"),
            )
            .select_from(Server)
            .join(total_gpus_per_server, Server.server_id == total_gpus_per_server.c.server_id)
            .outerjoin(used_gpus_per_server, Server.server_id == used_gpus_per_server.c.server_id)
            .join(GPU, Server.server_id == GPU.server_id)
            .where(
                GPU.model_short_ref.in_(supported_gpus),
                GPU.verified.is_(True),
                total_gpus_per_server.c.total_gpus >= chute.gpu_count,
                Server.locked.is_(False),
            )
            .order_by(Server.hourly_cost.asc(), text("free_gpus ASC"))
        )
        async with get_session() as session:
            servers = (await session.execute(query)).unique().scalars()
        if not servers:
            logger.warning(f"No servers in inventory are capable of running {chute.chute_id=}")
            return

        # Iterate through servers to see if any *could* handle preemption.
        chute_counts = {}
        for chute_id, metrics in self.remote_metrics.get(chute.validator, {}).items():
            chute_counts[chute_id] = metrics.get("instance_count", 0)
        to_preempt = None
        target_server = None
        for server in servers:
            available_gpus = sum([1 for gpu in server.gpus if not gpu.deployment_id])
            if available_gpus >= chute.gpu_count:
                logger.info(
                    f"Server {server.name} already has {available_gpus=}, no preemption necessary!"
                )
                target_server = server
                break

            proposed_counts = deepcopy(chute_counts)
            to_delete = []
            for deployment in sorted(
                server.deployments, key=lambda d: chute_values.get(d.chute_id, 0.0)
            ):
                # Make sure we aren't pointlessly preempting (already have a deployment in progress).
                if deployment.chute_id == chute.chute_id:
                    logger.warning(
                        f"Attempting to preempt for {chute.chute_id=}, but deployment already exists: {deployment.deployment_id=}"
                    )
                    return

                # Can't preempt deployments that haven't been verified yet.
                if not deployment.verified_at:
                    logger.warning(
                        f"Cannot preempt unverified deployment: {deployment.deployment_id}"
                    )
                    continue

                # Can't preempt deployments that are <= 5 minutes since verification.
                age = datetime.now(timezone.utc).replace(
                    tzinfo=None
                ) - deployment.verified_at.replace(tzinfo=None)
                if age <= timedelta(minutes=5):
                    logger.warning(
                        f"Cannot preempt {deployment.deployment_id=}, verification age is only {age}"
                    )
                    continue

                # If we'd be left with > 1 instance, we can preempt.
                if proposed_counts.get(deployment.chute_id, 0) > 1:
                    to_delete.append(deployment.deployment_id)
                    available_gpus += len(deployment.gpus)
                    proposed_counts[deployment.chute_id] -= 1
                elif deployment.chute_id in proposed_counts:
                    # Only allow 0 global replicas if we aren't getting invocations.
                    message = (
                        f"Preempting {deployment.deployment_id=} would leave no global instances!"
                    )
                    if (last_invoked := last_invocations.get(deployment.chute_id)) is not None:
                        time_since_invoked = (
                            datetime.now(timezone.utc).replace(tzinfo=None) - last_invoked
                        )
                        if time_since_invoked >= timedelta(minutes=10):
                            to_delete.append(deployment.deployment_id)
                            available_gpus += len(deployment.gpus)
                            proposed_counts[deployment.chute_id] -= 1
                        else:
                            logger.warning(message)
                    else:
                        logger.warning(message)

                # Would we reach a sufficient number of free GPUs?
                if available_gpus >= chute.gpu_count:
                    logger.info(f"Found a server to preempt deployments on: {server.name}")
                    to_preempt = to_delete
                    target_server = server
                    break
            if target_server:
                break
        if not target_server:
            logger.warning(
                f"Could not find a server with sufficient preemptable deployments for {chute.chute_id=}"
            )
            return

        # Do the preemption.
        if to_preempt:
            logger.info(f"Preempting deployments to make room for {chute.chute_id=}: {to_preempt}")
            for deployment_id in to_preempt:
                await self.undeploy(deployment_id)

        # Deploy on our target server.
        deployment = None
        try:
            deployment, k8s_dep, k8s_svc = await k8s.deploy_chute(
                chute.chute_id, target_server.server_id
            )
            logger.success(
                f"Successfully deployed {chute.chute_id=} via preemption on {server.server_id=}: {deployment.deployment_id=}"
            )
            await self.announce_deployment(deployment)
        except DeploymentFailure as exc:
            logger.error(
                f"Error attempting to deploy {chute.chute_id=} on {server.server_id=} via preemption: {exc}\n{traceback.format_exc()}"
            )
            if deployment:
                await self.undeploy(deployment.deployment_id)

    async def scale_chute(self, chute: Chute, desired_count: int, preempt: bool = False):
        """
        Scale up or down a chute.

        MINERS: This is probably the most critical function to optimize.
        """
        async with self._scale_lock:
            while (
                current_count := await self.count_deployments(
                    chute.chute_id, chute.version, chute.validator
                )
            ) != desired_count:
                # Scale down?
                if current_count > desired_count:
                    # MINERS: You'll want to figure out the best strategy for selecting deployments to purge.
                    # Examples:
                    # - undeploy on whichever server already has the most GPUs free so that the server
                    #   is more capable of allocating larger chutes when they are needed
                    # - undeploy on whichever server is the most expensive, e.g. if you have a chute
                    #   running on an h100 instance but the node selector only really needs a t4
                    # - consider both when counts are equal
                    # The default selects the deployment which when removed results in highest free GPU count on that server.
                    if (deployment := await self.optimal_scale_down_deployment(chute)) is not None:
                        await self.undeploy(deployment.deployment_id)
                    else:
                        logger.error(f"Scale down impossible right now, sorry: {chute.chute_id}")
                        return

                # Scale up?
                else:
                    # MINERS: You'll also want to figure out the best strategy for selecting servers here.
                    # Examples:
                    # - select server with the fewest GPUs available which suite the chute, like bin-packing
                    # - select the cheapest server that is capable of running the chute
                    # - select the server which already has the image and/or model warm (would be custom)
                    if (server := await self.optimal_scale_up_server(chute)) is None:
                        logger.warning(
                            f"No servers available to accept additional chute deployment: {chute.chute_id}"
                        )
                        # If no server can accept the new capacity, and preempt is true, we need to
                        # figure out which deployment(s) to remove.
                        if preempt:
                            await self.preempting_deploy(chute)
                        return

                    else:
                        logger.info(
                            f"Attempting to deploy {chute.chute_id=} on {server.server_id=}"
                        )
                        deployment = None
                        try:
                            deployment, k8s_dep, k8s_svc = await k8s.deploy_chute(
                                chute.chute_id, server.server_id
                            )
                            logger.success(
                                f"Successfully deployed {chute.chute_id=} on {server.server_id=}: {deployment.deployment_id=}"
                            )
                            await self.announce_deployment(deployment)
                        except DeploymentFailure as exc:
                            logger.error(
                                f"Error attempting to deploy {chute.chute_id=} on {server.server_id=}: {exc}\n{traceback.format_exc()}"
                            )
                            if deployment:
                                await self.undeploy(deployment.deployment_id)
                            return

    async def reconcile(self):
        """
        Put our local system back in harmony with the validators.
        """
        try:
            await self.remote_refresh_all()
        except Exception as exc:
            logger.error(f"Failed to refresh remote resources: {exc}")
            return

        # Get the chutes currently undergoing a rolling update.
        updating = {}
        for validator in settings.validators:
            updating[validator.hotkey] = {}
            async with aiohttp.ClientSession(raise_for_status=True) as session:
                async with session.get(f"{validator.api}/chutes/rolling_updates") as resp:
                    for item in await resp.json():
                        updating[validator.hotkey][item["chute_id"]] = item

        # Compare local items to validators' inventory.
        tasks = []
        chutes_to_remove = set()
        all_chutes = set()
        all_deployments = set()
        all_instances = set()
        k8s_chutes = await k8s.get_deployed_chutes()
        k8s_chute_ids = {c["deployment_id"] for c in k8s_chutes}
        async with get_session() as session:
            # Clean up based on deployments/instances.
            async for row in (await session.stream(select(Deployment))).unique():
                deployment = row[0]
                if deployment.instance_id and deployment.instance_id not in (
                    self.remote_instances.get(deployment.validator) or {}
                ):
                    logger.warning(
                        f"Deployment: {deployment.deployment_id} (instance_id={deployment.instance_id}) on validator {deployment.validator} not found"
                    )
                    tasks.append(
                        asyncio.create_task(
                            self.instance_deleted({"instance_id": deployment.instance_id})
                        )
                    )

                remote = (self.remote_chutes.get(deployment.validator) or {}).get(
                    deployment.chute_id
                )
                if not remote or remote["version"] != deployment.version:
                    update = updating.get(deployment.validator, {}).get(deployment.chute_id)
                    if update:
                        logger.warning(f"Skipping reconciliation for chute with rolling {update=}")
                        all_deployments.add(deployment.deployment_id)
                        if deployment.instance_id:
                            all_instances.add(deployment.instance_id)
                        continue
                    logger.warning(
                        f"Chute: {deployment.chute_id} version={deployment.version} on validator {deployment.validator} not found"
                    )
                    identifier = (
                        f"{deployment.validator}:{deployment.chute_id}:{deployment.version}"
                    )
                    if identifier not in chutes_to_remove:
                        chutes_to_remove.add(identifier)
                        tasks.append(
                            asyncio.create_task(
                                self.chute_deleted(
                                    {
                                        "chute_id": deployment.chute_id,
                                        "version": deployment.version,
                                        "validator": deployment.validator,
                                    }
                                )
                            )
                        )

                # Delete any deployments from the DB that either never made it past the stub stage or that aren't in k8s anymore.
                if not deployment.stub and deployment.deployment_id not in k8s_chute_ids:
                    logger.warning(
                        f"Deployment has disappeared from kubernetes: {deployment.deployment_id}"
                    )
                    if deployment.instance_id:
                        if (vali := validator_by_hotkey(deployment.validator)) is not None:
                            await self.purge_validator_instance(
                                vali, deployment.chute_id, deployment.instance_id
                            )
                    await session.delete(deployment)

                elif (deployment.stub or not deployment.instance_id) and datetime.now(
                    timezone.utc
                ) - deployment.created_at >= timedelta(minutes=30):
                    logger.warning(
                        f"Deployment is still a stub after 30 minutes, deleting! {deployment.deployment_id}"
                    )
                    await session.delete(deployment)

                # Check for crashlooping deployments.
                if (
                    not deployment.active
                    or not deployment.verified_at
                    and datetime.now(timezone.utc) - deployment.created_at >= timedelta(minutes=5)
                ):
                    try:
                        kd = await k8s.get_deployment(deployment.deployment_id)
                    except Exception as exc:
                        if "Not Found" in str(exc) or "(404)" in str(exc):
                            await self.undeploy(deployment.deployment_id)
                        continue

                    destroyed = False
                    for pod in kd["pods"]:
                        if (
                            pod["restart_count"] > 3
                            and pod.get("state", {}).get("waiting", {}).get("reason")
                            == "CrashLoopBackOff"
                        ):
                            logger.warning(
                                f"Deployment cannot run, purging: {deployment.deployment_id} and banning {deployment.chute_id=}"
                            )
                            await self.undeploy(deployment.deployment_id)
                            destroyed = True

                            # Blacklist chutes that crashloop, although this could be dangerous if the crashes
                            # are not because of the chutes themselves...
                            if (
                                chute := await self.load_chute(
                                    deployment.chute_id, deployment.version, deployment.validator
                                )
                            ) is not None:
                                chute.ban_reason = (
                                    "Chute reached crashloop/terminated state and never ran."
                                )
                            break
                    if destroyed:
                        continue

                # Track the list of deployments so we can reconcile with k8s state.
                all_deployments.add(deployment.deployment_id)
                if deployment.instance_id:
                    all_instances.add(deployment.instance_id)
            await session.commit()

            # Purge validator instances not deployed locally.
            for validator, instances in self.remote_instances.items():
                if (vali := validator_by_hotkey(validator)) is None:
                    continue
                for instance_id, data in instances.items():
                    if instance_id not in all_instances:
                        chute_id = data["chute_id"]
                        logger.warning(
                            f"Found validator {chute_id=} {instance_id=} not deployed locally!"
                        )
                        await self.purge_validator_instance(vali, chute_id, instance_id)

            # Purge k8s deployments that aren't tracked anymore.
            for deployment_id in k8s_chute_ids - all_deployments:
                logger.warning(
                    f"Removing kubernetes deployment that is no longer tracked: {deployment_id}"
                )
                tasks.append(asyncio.create_task(self.undeploy(deployment_id)))

            # GPUs that no longer exist in validator inventory.
            all_gpus = []
            for nodes in self.remote_nodes.values():
                all_gpus += list(nodes)
            local_gpu_ids = set()
            async for row in (await session.stream(select(GPU))).unique():
                gpu = row[0]
                local_gpu_ids.add(gpu.gpu_id)
                if gpu.gpu_id not in all_gpus:
                    logger.warning(
                        f"GPU {gpu.gpu_id} is no longer in validator {gpu.validator} inventory"
                    )
                    # XXX we need this reconciliation somehow, but API downtime is really problematic here...
                    # tasks.append(
                    #     asyncio.create_task(
                    #         self.gpu_deleted({"gpu_id": gpu.gpu_id, "validator": gpu.validator})
                    #     )
                    # )

            # XXX this also seems problematic currently :thinking:
            ## GPUs in validator inventory that don't exist locally.
            # for validator_hotkey, nodes in self.remote_nodes.items():
            #    for gpu_id in nodes:
            #        if gpu_id not in local_gpu_ids:
            #            logger.warning(
            #                f"Found GPU in inventory of {validator_hotkey} that is not local: {gpu_id}"
            #            )
            #            if (validator := validator_by_hotkey(validator_hotkey)) is not None:
            #                await self.remove_gpu_from_validator(validator, gpu_id)

            # Chutes that were removed/outdated.
            async for row in await session.stream(select(Chute)):
                chute = row[0]
                identifier = f"{chute.validator}:{chute.chute_id}:{chute.version}"
                all_chutes.add(identifier)
                remote = (self.remote_chutes.get(chute.validator) or {}).get(chute.chute_id)
                if (
                    not remote
                    or remote["version"] != chute.version
                    and identifier not in chutes_to_remove
                ):
                    update = updating.get(chute.validator, {}).get(chute.chute_id)
                    if update:
                        logger.warning(f"Skipping reconciliation for chute with rolling {update=}")
                        continue
                    logger.warning(
                        f"Chute: {chute.chute_id} version={chute.version} on validator {chute.validator} not found: {remote=}"
                    )
                    tasks.append(
                        asyncio.create_task(
                            self.chute_deleted(
                                {
                                    "chute_id": chute.chute_id,
                                    "version": chute.version,
                                    "validator": chute.validator,
                                }
                            )
                        )
                    )
                    chutes_to_remove.add(identifier)

            # New chutes.
            for validator, chutes in self.remote_chutes.items():
                for chute_id, config in chutes.items():
                    if f"{validator}:{chute_id}:{config['version']}" not in all_chutes:
                        update = updating.get(validator, {}).get(chute_id)
                        if update:
                            logger.warning(
                                f"Skipping chute reconciliation for chute with rolling {update=}"
                            )
                            continue
                        logger.info(f"Found a new/untracked chute: {chute_id}")
                        tasks.append(
                            asyncio.create_task(
                                self.chute_created(
                                    {
                                        "chute_id": chute_id,
                                        "version": config["version"],
                                        "validator": validator,
                                    }
                                )
                            )
                        )

            # Kubernetes nodes (aka servers).
            nodes = await k8s.get_kubernetes_nodes()
            node_ids = {node["server_id"] for node in nodes}
            all_server_ids = set()
            servers = (await session.execute(select(Server))).unique().scalars()
            for server in servers:
                if server.server_id not in node_ids:
                    logger.warning(f"Server {server.server_id} no longer in kubernetes node list!")
                    tasks.append(
                        asyncio.create_task(self.server_deleted({"server_id": server.server_id}))
                    )
                all_server_ids.add(server.server_id)

            # XXX We won't do the opposite (remove k8s nodes that aren't tracked) because they could be in provisioning status.
            for node_id in node_ids:
                if node_id not in all_server_ids:
                    logger.warning(f"Server/node {node_id} not tracked in inventory, ignoring...")

            await asyncio.gather(*tasks)

    async def reconciler(self):
        """
        Reconcile on a regular basis.
        """
        while True:
            await asyncio.sleep(600)
            try:
                await self.reconcile()
            except Exception as exc:
                logger.error(
                    f"Unexpected error in reconciliation loop: {exc}\n{traceback.format_exc()}"
                )


async def main():
    gepetto = Gepetto()
    await gepetto.run()


if __name__ == "__main__":
    asyncio.run(main())
