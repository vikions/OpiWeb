from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from eth_utils import is_address
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds, OpenOrderParams, OrderType

from .polymarket.clob_trading import build_builder_config, normalize_order_id

from .config import CHAIN_ID, CLOB_HOST

_DUMMY_PRIVATE_KEY = "0x" + "1" * 64


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
        return dict(self.order_data)


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
