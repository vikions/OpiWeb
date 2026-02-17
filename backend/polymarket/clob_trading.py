from __future__ import annotations

import os
from typing import Any, Optional

from dotenv import load_dotenv
from py_builder_signing_sdk.config import (
    BuilderApiKeyCreds,
    BuilderConfig,
    RemoteBuilderConfig,
)

load_dotenv()


def _read_builder_env() -> dict[str, Optional[str]]:
    return {
        "api_key": os.getenv("BUILDER_API_KEY"),
        "api_secret": os.getenv("BUILDER_API_SECRET") or os.getenv("BUILDER_SECRET"),
        "api_passphrase": os.getenv("BUILDER_API_PASSPHRASE")
        or os.getenv("BUILDER_PASS_PHRASE")
        or os.getenv("BUILDER_PASSPHRASE"),
        "signing_url": os.getenv("BUILDER_SIGNING_URL"),
    }


def build_builder_config() -> BuilderConfig:
    env = _read_builder_env()

    if env["api_key"] and env["api_secret"] and env["api_passphrase"]:
        return BuilderConfig(
            local_builder_creds=BuilderApiKeyCreds(
                key=env["api_key"],
                secret=env["api_secret"],
                passphrase=env["api_passphrase"],
            )
        )

    if env["signing_url"]:
        return BuilderConfig(
            remote_builder_config=RemoteBuilderConfig(url=str(env["signing_url"]))
        )

    raise ValueError(
        "Builder credentials are not configured. Set BUILDER_API_KEY/BUILDER_API_SECRET/"
        "BUILDER_API_PASSPHRASE (or BUILDER_SECRET/BUILDER_PASS_PHRASE), "
        "or set BUILDER_SIGNING_URL."
    )


def normalize_order_id(response: Any) -> Optional[str]:
    if response is None:
        return None

    if hasattr(response, "orderID"):
        return str(response.orderID)

    if hasattr(response, "order_id"):
        return str(response.order_id)

    if isinstance(response, dict):
        raw = response.get("orderID") or response.get("order_id") or response.get("id")
        if raw:
            return str(raw)

    return None
