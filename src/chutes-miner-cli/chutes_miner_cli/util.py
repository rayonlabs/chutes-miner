#!/usr/bin/env python

import json
import hashlib
import time
from substrateinterface import Keypair
from typing import Dict, Any
from chutes_miner_cli.constants import (
    VALIDATOR_HEADER,
    HOTKEY_HEADER,
    MINER_HEADER,
    NONCE_HEADER,
    SIGNATURE_HEADER,
)


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
    hotkey: str,
    payload: Dict[str, Any] | str | None = None,
    purpose: str = None,
    remote: bool = False,
):
    """
    Generate a signed request (for miner requests to validators).
    """
    hotkey_data = json.loads(open(hotkey).read())
    nonce = str(int(time.time()))
    headers = {
        MINER_HEADER: hotkey_data["ss58Address"],
        NONCE_HEADER: nonce,
    }
    if remote:
        headers[HOTKEY_HEADER] = headers.pop(MINER_HEADER)
    signature_string = None
    payload_string = None
    if payload is not None:
        if isinstance(payload, (list, dict)):
            headers["Content-Type"] = "application/json"
            payload_string = json.dumps(payload)
        else:
            payload_string = payload
        signature_string = get_signing_message(
            hotkey_data["ss58Address"],
            nonce,
            payload_str=payload_string,
            purpose=None,
        )
    else:
        signature_string = get_signing_message(
            hotkey_data["ss58Address"], nonce, payload_str=None, purpose=purpose
        )
    if not remote:
        signature_string = hotkey_data["ss58Address"] + ":" + signature_string
        headers[VALIDATOR_HEADER] = headers[MINER_HEADER]
    keypair = Keypair.create_from_seed(hotkey_data["secretSeed"])
    headers[SIGNATURE_HEADER] = keypair.sign(signature_string.encode()).hex()
    return headers, payload_string
