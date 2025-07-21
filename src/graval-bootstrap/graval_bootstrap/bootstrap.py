"""
GraVal Bootstrap: spin up a simple FastAPI server for GPU verficiation.
"""

import time
import hashlib
import argparse
import uvicorn
import asyncio
import json
import base64
import aiohttp
from typing import Optional
from pydantic import BaseModel, Field
from graval.miner import Miner
from substrateinterface import Keypair, KeypairType
from fastapi import FastAPI, Request, status, HTTPException
from fastapi.responses import PlainTextResponse


class Challenge(BaseModel):
    seed: int = Field(..., ge=0)
    iterations: int = Field(1, ge=1, le=10)
    ciphertext: Optional[dict[str, str]] = {}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
    )
    parser.add_argument(
        "--validator-whitelist",
        type=str,
    )
    parser.add_argument(
        "--hotkey",
        type=str,
    )
    args = parser.parse_args()

    miner = Miner()
    miner._uuids = [miner.get_device_info(i)["uuid"] for i in range(miner._device_count)]
    miner._init_seed = None
    miner._init_iter = None
    app = FastAPI(
        title="GraVal bootstrap",
        description="GPU info plz",
        version="0.2.5",
    )
    gpu_lock = asyncio.Lock()

    def verify_request(request: Request, whitelist: list[str], extra_key: str = "graval") -> None:
        """
        Verify the authenticity of a request.
        """
        if not whitelist or not whitelist[0]:
            return
        miner_hotkey = request.headers.get("X-Chutes-Miner")
        validator_hotkey = request.headers.get("X-Chutes-Validator")
        nonce = request.headers.get("X-Chutes-Nonce")
        signature = request.headers.get("X-Chutes-Signature")
        if (
            any(not v for v in [miner_hotkey, validator_hotkey, nonce, signature])
            or miner_hotkey != args.hotkey
            or validator_hotkey not in whitelist
            or int(time.time()) - int(nonce) >= 30
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="go away {miner_hotkey=} {validator_hotkey=} {whitelist=} {nonce=} {signature=}",
            )
        signature_string = ":".join(
            [
                miner_hotkey,
                validator_hotkey,
                nonce,
                extra_key,
            ]
        )
        if not Keypair(ss58_address=validator_hotkey, crypto_type=KeypairType.SR25519).verify(
            signature_string, bytes.fromhex(signature)
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"go away -- bad signature: {signature_string} -- {validator_hotkey=}",
            )

    @app.get("/ping", response_class=PlainTextResponse)
    async def ping():
        return "pong"

    @app.get("/devices")
    async def get_devices(request: Request):
        """
        Get the list of devices, only used by internal components.
        """
        verify_request(request, [args.hotkey])
        return {
            "devices": [miner.get_device_info(idx) for idx in range(miner._device_count)],
        }

    @app.post("/prove")
    async def generate_proof(challenge: Challenge, request: Request):
        """
        Generate a proof for the incoming challenge, along with decrypting the payload.
        """
        request_body = await request.body()
        print(f"Received proof request: {request_body=}")
        sha2 = hashlib.sha256(request_body).hexdigest()
        verify_request(request, (args.validator_whitelist or "").split(","), extra_key=sha2)
        async with gpu_lock:
            proofs = miner.prove(challenge.seed, iterations=challenge.iterations)
            return_value = {
                "devices": [
                    {k: v for k, v in miner.get_device_info(idx).items() if k != "work_product"}
                    for idx in range(miner._device_count)
                ],
                "seed": challenge.seed,
                "proof": proofs,
                "plaintext": {},
            }

            # Decrypt all ciphertexts, if provided.
            for device_uuid, data in challenge.ciphertext.items():
                try:
                    device_index = miner._uuids.index(device_uuid)
                    print(
                        f"Decrypting {data=} for GPU {device_uuid} {device_index=} from seed {challenge.seed}"
                    )
                    bytes_ = base64.b64decode(data)
                    iv = bytes_[:16]
                    ciphertext = bytes_[16:]
                    return_value["plaintext"][device_uuid] = miner.decrypt(
                        challenge.seed,
                        ciphertext,
                        iv,
                        len(ciphertext),
                        device_index,
                    )
                except Exception as exc:
                    print(
                        f"Failed to decrypt on GPU {device_uuid} from seed {challenge.seed}: {exc=}"
                    )
                    raise

            return return_value

    @app.get("/info", response_class=PlainTextResponse)
    async def info_challenge(request: Request, challenge: str):
        """
        Perform a device info challenge.
        """
        verify_request(request, (args.validator_whitelist or "").split(","))
        return miner.process_device_info_challenge(challenge)

    @app.post("/remote_token", response_class=PlainTextResponse)
    async def get_remote_token(request: Request):
        """
        Load a remote token to check inbound vs outbound IPs.
        """
        verify_request(request, (args.validator_whitelist or "").split(","))
        token_url = json.loads(await request.body())["token_url"]
        async with aiohttp.ClientSession() as session:
            async with session.get(token_url) as resp:
                return (await resp.json())["token"]

    uvicorn.run(app=app, host="0.0.0.0", port=args.port)


if __name__ == "__main__":
    main()
