from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

import requests
from eth_utils import is_address

from .integrations.dome_client import DomeClient
from .integrations.market_fallback import get_all_markets

from .config import CHAIN_ID, DEFAULT_EXCHANGE_ADDRESS


_ADDRESS_RE = re.compile(r"0x[a-fA-F0-9]{40}")
_PROXY_KEYS = {
    "proxy",
    "proxywallet",
    "proxy_wallet",
    "proxyaddress",
    "proxy_address",
    "safe",
    "safeaddress",
    "safe_address",
}


def _normalize_addr(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    value = value.strip()
    if is_address(value):
        return value
    match = _ADDRESS_RE.search(value)
    if match and is_address(match.group(0)):
        return match.group(0)
    return None


def _find_proxy_in_obj(obj: Any, eoa_lower: str) -> Optional[str]:
    if isinstance(obj, dict):
        for key, value in obj.items():
            key_norm = str(key).replace("-", "_").lower()
            addr = _normalize_addr(value)
            if addr and key_norm in _PROXY_KEYS and addr.lower() != eoa_lower:
                return addr

            nested = _find_proxy_in_obj(value, eoa_lower)
            if nested:
                return nested

    elif isinstance(obj, list):
        for item in obj:
            nested = _find_proxy_in_obj(item, eoa_lower)
            if nested:
                return nested

    return None


def _find_any_alt_address(obj: Any, eoa_lower: str) -> Optional[str]:
    if isinstance(obj, dict):
        for value in obj.values():
            addr = _normalize_addr(value)
            if addr and addr.lower() != eoa_lower:
                return addr
            nested = _find_any_alt_address(value, eoa_lower)
            if nested:
                return nested
    elif isinstance(obj, list):
        for item in obj:
            nested = _find_any_alt_address(item, eoa_lower)
            if nested:
                return nested
    return None


def _extract_token_ids_from_market(market: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    def get_any(source: Dict[str, Any], keys: List[str]) -> Optional[str]:
        for key in keys:
            if key in source and source[key] not in (None, ""):
                return str(source[key])
        return None

    yes = get_any(
        market,
        [
            "clob_token_yes",
            "clobTokenYes",
            "yes_token_id",
            "yesTokenId",
            "token_yes",
        ],
    )
    no = get_any(
        market,
        [
            "clob_token_no",
            "clobTokenNo",
            "no_token_id",
            "noTokenId",
            "token_no",
        ],
    )

    if yes and no:
        return yes, no

    dome_raw = market.get("dome_raw") if isinstance(market.get("dome_raw"), dict) else {}
    side_a_id = dome_raw.get("side_a_id") or dome_raw.get("sideAId")
    side_b_id = dome_raw.get("side_b_id") or dome_raw.get("sideBId")
    side_a_label = str(dome_raw.get("side_a_label") or "").lower()
    side_b_label = str(dome_raw.get("side_b_label") or "").lower()

    if not yes and side_a_id and "yes" in side_a_label:
        yes = str(side_a_id)
    if not no and side_b_id and "no" in side_b_label:
        no = str(side_b_id)

    if not yes and side_b_id and "yes" in side_b_label:
        yes = str(side_b_id)
    if not no and side_a_id and "no" in side_a_label:
        no = str(side_a_id)

    return yes, no


def _extract_token_ids_from_gamma(market_id: str) -> Tuple[Optional[str], Optional[str]]:
    try:
        response = requests.get(
            "https://gamma-api.polymarket.com/markets",
            params={"id": market_id},
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()

        if isinstance(payload, list):
            markets = payload
        elif isinstance(payload, dict):
            markets = payload.get("markets") or []
        else:
            markets = []

        if not markets:
            return None, None

        m = markets[0]

        outcomes = m.get("outcomes")
        if isinstance(outcomes, str):
            import json

            try:
                outcomes = json.loads(outcomes)
            except Exception:
                outcomes = None

        clob_token_ids = m.get("clobTokenIds") or m.get("clob_token_ids")
        if isinstance(clob_token_ids, str):
            import json

            try:
                clob_token_ids = json.loads(clob_token_ids)
            except Exception:
                clob_token_ids = None

        yes = None
        no = None
        if isinstance(outcomes, list) and isinstance(clob_token_ids, list):
            for outcome, token in zip(outcomes, clob_token_ids):
                out = str(outcome).lower()
                if "yes" in out:
                    yes = str(token)
                elif "no" in out:
                    no = str(token)

        return yes, no
    except Exception:
        return None, None


class TradingContextResolver:
    def __init__(self):
        self._dome = None
        try:
            self._dome = DomeClient()
        except Exception:
            self._dome = None

    def resolve(self, eoa_address: str) -> Dict[str, Any]:
        eoa_lower = eoa_address.lower()
        context = {
            "eoa_address": eoa_address,
            "trading_address": eoa_address,
            "funder_address": None,
            "signature_type": 0,
            "mode": "eoa",
            "chain_id": CHAIN_ID,
            "exchange_address": DEFAULT_EXCHANGE_ADDRESS,
            "dome_wallet": None,
        }

        if not self._dome:
            return context

        try:
            wallet_data = self._dome.get_wallet(eoa=eoa_address)
            context["dome_wallet"] = wallet_data

            proxy = _find_proxy_in_obj(wallet_data, eoa_lower)
            if not proxy:
                proxy = _find_any_alt_address(wallet_data, eoa_lower)

            if proxy and proxy.lower() != eoa_lower:
                context.update(
                    {
                        "trading_address": proxy,
                        "funder_address": proxy,
                        "signature_type": 2,
                        "mode": "proxy",
                    }
                )
        except Exception as exc:
            context["resolver_warning"] = str(exc)

        return context

    def search(self, query: str, limit: int = 20) -> List[Dict[str, Any]]:
        if not self._dome:
            return []

        result = self._dome.search_markets(query, limit=limit)
        found = result.get("markets_found") or []

        config_by_polymarket = {}
        for market in get_all_markets().values():
            pid = market.get("polymarket_id")
            if pid:
                config_by_polymarket[str(pid)] = market

        rows: List[Dict[str, Any]] = []
        for market in found:
            market_id = str(market.get("market_id") or "")
            yes_token, no_token = _extract_token_ids_from_market(market)

            if (not yes_token or not no_token) and market_id:
                gy, gn = _extract_token_ids_from_gamma(market_id)
                yes_token = yes_token or gy
                no_token = no_token or gn

            if (not yes_token or not no_token) and market_id in config_by_polymarket:
                cfg = config_by_polymarket[market_id]
                yes_token = yes_token or str((cfg.get("tokens") or {}).get("yes"))
                no_token = no_token or str((cfg.get("tokens") or {}).get("no"))

            rows.append(
                {
                    "market_id": market_id,
                    "title": str(market.get("question") or market.get("title") or "Untitled"),
                    "liquidity": float(market.get("liquidity") or 0),
                    "opportunity_score": float(market.get("opportunity_score") or 0),
                    "yes_token_id": yes_token,
                    "no_token_id": no_token,
                    "source": "dome",
                }
            )

        return rows
