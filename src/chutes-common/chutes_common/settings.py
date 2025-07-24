import os
import json
from typing import List
from pydantic import BaseModel, Field
from substrateinterface import Keypair
from pydantic_settings import BaseSettings


class Validator(BaseModel):
    hotkey: str
    registry: str
    api: str
    socket: str


class MinerSettings(BaseSettings):
    _validators: List[Validator] = []

    miner_ss58: str = os.environ["MINER_SS58"]
    miner_keypair: Keypair = Keypair.create_from_seed(os.environ["MINER_SEED"])
    validators_json: str = os.environ["VALIDATORS"]

    @property
    def validators(self) -> List[Validator]:
        if self._validators:
            return self._validators
        data = json.loads(self.validators_json)
        self._validators = [Validator(**item) for item in data["supported"]]
        return self._validators


miner_settings = MinerSettings()


class RedisSettings(BaseSettings):
    redis_url: str = Field(default="redis://redis:6379", description="Redis URL")


# redis_settings = RedisSettings()
