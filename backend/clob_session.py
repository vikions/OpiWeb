from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from eth_utils import is_address, to_checksum_address
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import (
    ApiCreds,
    BalanceAllowanceParams,
    OpenOrderParams,
    OrderType,
)

from .polymarket.clob_trading import build_builder_config, normalize_order_id

from .config import CHAIN_ID, CLOB_HOST

_DUMMY_PRIVATE_KEY = "0x" + "1" * 64
_MAX_SAFE_JSON_INT = 9_007_199_254_740_991


def _to_int(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be integer-like, got bool")
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("0x") or text.startswith("0X"):
            return int(text, 16)
        return int(text)
    return int(value)


def _normalize_side(value: Any) -> str:
    if isinstance(value, str):
        text = value.strip().upper()
        if text in {"BUY", "SELL"}:
            return text
    n = _to_int(value, "side")
    if n == 0:
        return "BUY"
    if n == 1:
        return "SELL"
    raise ValueError(f"side must be BUY/SELL or 0/1, got {value!r}")


def _normalize_addr(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not is_address(text):
        raise ValueError(f"{field} is not a valid address: {value!r}")
    return to_checksum_address(text)


def _normalize_signed_order_payload(signed_order: Dict[str, Any]) -> Dict[str, Any]:
    signature = str(signed_order.get("signature") or "").strip()
    if not signature:
        raise ValueError("signature is required")

    salt = _to_int(signed_order.get("salt"), "salt")
    if salt < 0 or salt > _MAX_SAFE_JSON_INT:
        raise ValueError(
            f"salt must be in [0, {_MAX_SAFE_JSON_INT}] for CLOB JSON payload compatibility"
        )

    normalized = {
        "salt": salt,
        "maker": _normalize_addr(signed_order.get("maker"), "maker"),
        "signer": _normalize_addr(signed_order.get("signer"), "signer"),
        "taker": _normalize_addr(signed_order.get("taker"), "taker"),
        "tokenId": str(_to_int(signed_order.get("tokenId"), "tokenId")),
        "makerAmount": str(_to_int(signed_order.get("makerAmount"), "makerAmount")),
        "takerAmount": str(_to_int(signed_order.get("takerAmount"), "takerAmount")),
        "expiration": str(_to_int(signed_order.get("expiration"), "expiration")),
        "nonce": str(_to_int(signed_order.get("nonce"), "nonce")),
        "feeRateBps": str(_to_int(signed_order.get("feeRateBps"), "feeRateBps")),
        "side": _normalize_side(signed_order.get("side")),
        "signatureType": int(_to_int(signed_order.get("signatureType"), "signatureType")),
        "signature": signature,
    }
    return normalized


class SessionAddressSigner:
    def __init__(self, address: str, chain_id: int):
        self._address = address
        self._chain_id = chain_id

    def address(self):
        return self._address

    def get_chain_id(self):
        return self._chain_id

    def sign(self, message_hash):
        raise RuntimeError("SessionAddressSigner cannot sign messages")


@dataclass
class SignedOrderPayload:
    order_data: Dict[str, Any]

    def dict(self):
        return _normalize_signed_order_payload(self.order_data)


class Level2SessionClobClient:
    def __init__(
        self,
        eoa_address: str,
        creds: Dict[str, str],
        funder_address: Optional[str] = None,
        signature_type: int = 0,
    ):
        if not is_address(eoa_address):
            raise ValueError("Invalid eoa_address")

        if funder_address and not is_address(funder_address):
            raise ValueError("Invalid funder_address")

        api_creds = ApiCreds(
            api_key=creds["api_key"],
            api_secret=creds["api_secret"],
            api_passphrase=creds["api_passphrase"],
        )

        self.client = ClobClient(
            host=CLOB_HOST,
            chain_id=CHAIN_ID,
            key=_DUMMY_PRIVATE_KEY,
            creds=api_creds,
            signature_type=signature_type,
            funder=funder_address,
            builder_config=build_builder_config(),
        )

        self.client.signer = SessionAddressSigner(eoa_address, CHAIN_ID)

    def post_signed_order(
        self,
        signed_order: Dict[str, Any],
        order_type: str = "GTC",
    ) -> Dict[str, Any]:
        payload = SignedOrderPayload(order_data=signed_order)
        type_name = (order_type or "GTC").upper()
        post_type = getattr(OrderType, type_name, OrderType.GTC)
        response = self.client.post_order(payload, post_type)
        return {
            "status": "success",
            "order_id": normalize_order_id(response),
            "response": response,
        }

    def get_order(self, order_id: str) -> Dict[str, Any]:
        response = self.client.get_order(order_id)
        return {"status": "success", "order": response}

    def get_open_orders(
        self, market: Optional[str] = None, asset_id: Optional[str] = None
    ) -> Dict[str, Any]:
        params = OpenOrderParams(market=market, asset_id=asset_id)
        orders = self.client.get_orders(params=params)
        return {"status": "success", "orders": orders}

    def cancel_order(self, order_id: str) -> Dict[str, Any]:
        response = self.client.cancel(order_id)
        return {"status": "success", "response": response, "order_id": order_id}

    def get_balance_allowance(
        self, asset_type: str, token_id: Optional[str] = None
    ) -> Dict[str, Any]:
        params = BalanceAllowanceParams(
            asset_type=asset_type,
            token_id=token_id,
            signature_type=-1,
        )
        response = self.client.get_balance_allowance(params=params)
        return {"status": "success", "response": response}
