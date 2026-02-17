from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional

import requests


class DomeClient:
    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
        self.api_key = api_key or os.getenv("DOME_API_KEY")
        if not self.api_key:
            raise ValueError("DOME_API_KEY is required")

        self.base_url = (base_url or os.getenv("DOME_BASE_URL") or "https://api.domeapi.io/v1").rstrip("/")
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _safe_get(obj: Any, key: str, default: Any = None) -> Any:
        if isinstance(obj, dict):
            return obj.get(key, default)
        try:
            return getattr(obj, key)
        except Exception:
            return default

    @staticmethod
    def _to_float(value: Any, default: float = 0.0) -> float:
        try:
            if value is None:
                return default
            return float(value)
        except Exception:
            return default

    @staticmethod
    def _opportunity_score(liquidity: float, yes_price: float, volume_24h: float) -> float:
        liquidity_score = min(liquidity / 10_000.0, 1.0)
        price_uncertainty = 1.0 - abs(0.5 - yes_price) * 2.0
        volume_score = min(volume_24h / 5_000.0, 1.0)
        return round(liquidity_score * 0.4 + price_uncertainty * 0.3 + volume_score * 0.3, 3)

    def _empty_response(self) -> Dict[str, Any]:
        return {
            "markets_found": [],
            "best_market": None,
            "total_count": 0,
            "source": "dome",
        }

    def _search_raw(self, query: str, limit: int) -> List[Dict[str, Any]]:
        params = {"search": query, "status": "open", "limit": int(limit)}
        response = requests.get(
            f"{self.base_url}/polymarket/markets",
            headers=self.headers,
            params=params,
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict):
            markets = payload.get("markets") or []
            if isinstance(markets, list):
                return [m for m in markets if isinstance(m, dict)]
        return []

    def _transform_market(self, market: Dict[str, Any]) -> Dict[str, Any]:
        g = self._safe_get

        market_id = str(
            g(market, "market_id")
            or g(market, "id")
            or g(market, "market_slug")
            or ""
        )
        title = str(g(market, "title") or g(market, "question") or "Untitled")
        question = str(g(market, "question") or title)

        volume_total = self._to_float(g(market, "volume_total"), 0.0)
        volume_week = self._to_float(g(market, "volume_1_week"), 0.0)
        volume_month = self._to_float(g(market, "volume_1_month"), 0.0)
        volume_24h = volume_week / 7.0 if volume_week > 0 else volume_month / 30.0

        liquidity = self._to_float(g(market, "liquidity"), 0.0)
        if liquidity <= 0:
            liquidity = volume_total * 0.3

        side_a = g(market, "side_a") or {}
        side_b = g(market, "side_b") or {}
        side_a_id = g(side_a, "id")
        side_b_id = g(side_b, "id")
        side_a_label = str(g(side_a, "label") or "")
        side_b_label = str(g(side_b, "label") or "")

        yes_price = self._to_float(
            g(market, "current_yes_price"),
            self._to_float(g(market, "yes_price"), 0.5),
        )
        no_price = self._to_float(
            g(market, "current_no_price"),
            self._to_float(g(market, "no_price"), max(0.0, 1.0 - yes_price)),
        )

        opportunity_score = self._opportunity_score(liquidity, yes_price, volume_24h)

        return {
            "market_id": market_id,
            "market_slug": str(g(market, "market_slug") or ""),
            "title": title,
            "question": question,
            "liquidity": liquidity,
            "current_yes_price": yes_price,
            "current_no_price": no_price,
            "volume_24h": volume_24h,
            "volume_total": volume_total,
            "opportunity_score": opportunity_score,
            "active": bool((g(market, "end_time") or time.time() + 1) > time.time()),
            "tags": g(market, "tags") or [],
            "yes_label": g(market, "yes_label") or g(market, "yes_outcome"),
            "no_label": g(market, "no_label") or g(market, "no_outcome"),
            "dome_raw": {
                "condition_id": g(market, "condition_id"),
                "side_a_id": side_a_id,
                "side_b_id": side_b_id,
                "side_a_label": side_a_label,
                "side_b_label": side_b_label,
            },
            "clob_token_yes": g(market, "clob_token_yes"),
            "clob_token_no": g(market, "clob_token_no"),
            "yes_token_id": g(market, "yes_token_id"),
            "no_token_id": g(market, "no_token_id"),
        }

    def get_wallet(
        self,
        eoa: Optional[str] = None,
        proxy: Optional[str] = None,
        handle: Optional[str] = None,
        with_metrics: bool = False,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        keys = [bool(eoa), bool(proxy), bool(handle)]
        if sum(keys) != 1:
            raise ValueError("Provide exactly one of eoa, proxy, or handle")

        params: Dict[str, Any] = {}
        if eoa:
            params["eoa"] = eoa
        elif proxy:
            params["proxy"] = proxy
        else:
            params["handle"] = handle.lstrip("@") if handle else handle

        if with_metrics:
            params["with_metrics"] = "true"
            if start_time is not None:
                params["start_time"] = int(start_time)
            if end_time is not None:
                params["end_time"] = int(end_time)

        response = requests.get(
            f"{self.base_url}/polymarket/wallet",
            headers=self.headers,
            params=params,
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, dict) else None

    def search_markets(self, project_name: str, limit: int = 20) -> Dict[str, Any]:
        try:
            terms = [
                project_name,
                f"{project_name} token",
                f"{project_name} launch",
            ]
            markets: List[Dict[str, Any]] = []
            for term in terms:
                rows = self._search_raw(term, limit)
                if rows:
                    markets = rows
                    break

            if not markets:
                return self._empty_response()

            transformed = [self._transform_market(m) for m in markets]
            transformed.sort(key=lambda x: float(x.get("opportunity_score") or 0), reverse=True)

            return {
                "markets_found": transformed,
                "best_market": transformed[0] if transformed else None,
                "total_count": len(transformed),
                "source": "dome",
            }
        except Exception:
            return self._empty_response()
