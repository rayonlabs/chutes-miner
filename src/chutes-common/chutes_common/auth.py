"""
Authentication helpers.
"""

import time
import hashlib
import orjson as json
from loguru import logger
from typing import Dict, Any
from functools import lru_cache
from substrateinterface import Keypair, KeypairType
from fastapi import Request, status, HTTPException, Header
from chutes_common.constants import (
    HOTKEY_HEADER,
    MINER_HEADER,
    VALIDATOR_HEADER,
    SIGNATURE_HEADER,
    NONCE_HEADER,
)
from chutes_common.settings import miner_settings


@lru_cache(maxsize=32)
def get_keypair(ss58):
    """
    Helper to load keypairs efficiently.
    """
    return Keypair(ss58_address=ss58, crypto_type=KeypairType.SR25519)


def authorize(allow_miner=False, allow_validator=False, purpose: str = None):
    def _authorize(
        request: Request,
        validator: str | None = Header(None, alias=VALIDATOR_HEADER),
        miner: str | None = Header(None, alias=MINER_HEADER),
        nonce: str | None = Header(None, alias=NONCE_HEADER),
        signature: str | None = Header(None, alias=SIGNATURE_HEADER),
    ):
        """
        Verify the authenticity of a request.
        """
        allowed_signers = []
        if allow_miner:
            allowed_signers.append(miner_settings.miner_ss58)
        if allow_validator:
            allowed_signers += [validator.hotkey for validator in miner_settings.validators]
        if (
            any(not v for v in [miner, validator, nonce, signature])
            or miner != miner_settings.miner_ss58
            or validator not in allowed_signers
            or int(time.time()) - int(nonce) >= 30
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="go away (missing)"
            )
        signature_string = ":".join(
            [
                miner,
                validator,
                nonce,
                request.state.body_sha256 if request.state.body_sha256 else purpose,
            ]
        )
        if not get_keypair(validator).verify(signature_string, bytes.fromhex(signature)):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"go away: (sig): {request.state.body_sha256=} {signature_string=}",
            )

    return _authorize


def get_signing_message(
    hotkey: str,
    nonce: str,
    payload_str: str | bytes | None,
    purpose: str | None = None,
    payload_hash: str | None = None,
) -> str:
    """
    Get the signing message for a given hotkey, nonce, and payload.
    """
    if payload_str:
        if isinstance(payload_str, str):
            payload_str = payload_str.encode()
        return f"{hotkey}:{nonce}:{hashlib.sha256(payload_str).hexdigest()}"
    elif purpose:
        return f"{hotkey}:{nonce}:{purpose}"
    elif payload_hash:
        return f"{hotkey}:{nonce}:{payload_hash}"
    else:
        raise ValueError("Either payload_str or purpose must be provided")


def sign_request(
    payload: Dict[str, Any] | str | None = None, purpose: str = None, management: bool = False
):
    """
    Generate a signed request (for miner requests to validators).
    """
    nonce = str(int(time.time()))
    headers = {
        HOTKEY_HEADER: miner_settings.miner_ss58,
        NONCE_HEADER: nonce,
    }
    signature_string = None
    payload_string = None
    if payload is not None:
        if isinstance(payload, (list, dict)):
            headers["Content-Type"] = "application/json"
            payload_string = json.dumps(payload)
        else:
            payload_string = payload
        signature_string = get_signing_message(
            miner_settings.miner_ss58,
            nonce,
            payload_str=payload_string,
            purpose=None,
        )
    else:
        signature_string = get_signing_message(
            miner_settings.miner_ss58, nonce, payload_str=None, purpose=purpose
        )
    if management:
        signature_string = miner_settings.miner_ss58 + ":" + signature_string
        headers[MINER_HEADER] = headers.pop(HOTKEY_HEADER)
        headers[VALIDATOR_HEADER] = headers[MINER_HEADER]
    logger.debug(f"Signing message: {signature_string}")
    headers[SIGNATURE_HEADER] = miner_settings.miner_keypair.sign(signature_string.encode()).hex()
    return headers, payload_string
