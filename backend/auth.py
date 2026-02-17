from __future__ import annotations

import datetime as dt
from typing import Any, Dict

import requests
from eth_account import Account
from eth_account.messages import encode_defunct, encode_typed_data
from eth_utils import is_address
from fastapi import HTTPException

from .config import (
    CHAIN_ID,
    CLOB_AUTH_DOMAIN_NAME,
    CLOB_AUTH_DOMAIN_VERSION,
    CLOB_AUTH_MESSAGE,
    CLOB_HOST,
)


def validate_eth_address(address: str) -> str:
    if not address or not is_address(address):
        raise HTTPException(status_code=400, detail="Invalid EVM address")
    return address


def build_siwe_message(address: str, nonce: str, chain_id: int = CHAIN_ID) -> str:
    now = dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    return (
        "OpiPoliX Web Experiment\n"
        "Sign this message to authenticate.\n\n"
        f"Address: {address}\n"
        f"Chain ID: {chain_id}\n"
        f"Nonce: {nonce}\n"
        f"Issued At: {now}"
    )


def recover_personal_signer(message: str, signature: str) -> str:
    try:
        signable = encode_defunct(text=message)
        return Account.recover_message(signable, signature=signature)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid signature: {exc}") from exc


def clob_auth_typed_data(address: str, timestamp: int, nonce: int, chain_id: int) -> Dict[str, Any]:
    return {
        "types": {
            "EIP712Domain": [
                {"name": "name", "type": "string"},
                {"name": "version", "type": "string"},
                {"name": "chainId", "type": "uint256"},
            ],
            "ClobAuth": [
                {"name": "address", "type": "address"},
                {"name": "timestamp", "type": "string"},
                {"name": "nonce", "type": "uint256"},
                {"name": "message", "type": "string"},
            ],
        },
        "primaryType": "ClobAuth",
        "domain": {
            "name": CLOB_AUTH_DOMAIN_NAME,
            "version": CLOB_AUTH_DOMAIN_VERSION,
            "chainId": int(chain_id),
        },
        "message": {
            "address": address,
            "timestamp": str(timestamp),
            "nonce": int(nonce),
            "message": CLOB_AUTH_MESSAGE,
        },
    }


def recover_clob_auth_signer(
    address: str,
    signature: str,
    timestamp: int,
    nonce: int,
    chain_id: int,
) -> str:
    typed = clob_auth_typed_data(address, timestamp, nonce, chain_id)
    try:
        signable = encode_typed_data(full_message=typed)
        recovered = Account.recover_message(signable, signature=signature)
    except Exception as exc:
        raise HTTPException(
            status_code=400, detail=f"Invalid CLOB auth signature: {exc}"
        ) from exc

    if recovered.lower() != address.lower():
        raise HTTPException(status_code=400, detail="CLOB auth signer mismatch")

    return recovered


def derive_clob_api_creds(
    address: str,
    signature: str,
    timestamp: int,
    nonce: int,
) -> Dict[str, str]:
    headers = {
        "POLY_ADDRESS": address,
        "POLY_SIGNATURE": signature,
        "POLY_TIMESTAMP": str(timestamp),
        "POLY_NONCE": str(nonce),
    }

    create_url = f"{CLOB_HOST}/auth/api-key"
    derive_url = f"{CLOB_HOST}/auth/derive-api-key"

    create_resp = requests.post(create_url, headers=headers, timeout=10)
    if create_resp.ok:
        payload = create_resp.json()
    else:
        derive_resp = requests.get(derive_url, headers=headers, timeout=10)
        if not derive_resp.ok:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Failed to derive CLOB API credentials. "
                    f"create={create_resp.status_code}, derive={derive_resp.status_code}"
                ),
            )
        payload = derive_resp.json()

    api_key = payload.get("apiKey")
    api_secret = payload.get("secret")
    api_passphrase = payload.get("passphrase")

    if not api_key or not api_secret or not api_passphrase:
        raise HTTPException(status_code=400, detail="CLOB credential payload missing fields")

    return {
        "api_key": api_key,
        "api_secret": api_secret,
        "api_passphrase": api_passphrase,
    }
