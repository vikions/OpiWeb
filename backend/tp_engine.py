from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any, Dict, List, Optional

from .clob_session import Level2SessionClobClient
from .config import TP_MAX_MINUTES, TP_POLL_SECONDS
from .store import InMemoryStore


def _as_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.replace(",", "").strip()
        if not cleaned:
            return None
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def _collect_numeric_values(obj: Any, keys: List[str], out: List[float]) -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if str(k).lower() in keys:
                val = _as_float(v)
                if val is not None:
                    out.append(val)
            _collect_numeric_values(v, keys, out)
    elif isinstance(obj, list):
        for item in obj:
            _collect_numeric_values(item, keys, out)


def _collect_status(obj: Any) -> Optional[str]:
    if isinstance(obj, dict):
        for k, v in obj.items():
            if str(k).lower() in {"status", "state", "order_status"} and isinstance(v, str):
                return v.lower()
            nested = _collect_status(v)
            if nested:
                return nested
    elif isinstance(obj, list):
        for item in obj:
            nested = _collect_status(item)
            if nested:
                return nested
    return None


def extract_filled_tokens(order_payload: Dict[str, Any], entry_size_tokens: float) -> float:
    status_text = _collect_status(order_payload)
    if status_text and "filled" in status_text and "partial" not in status_text:
        return entry_size_tokens

    pct_values: List[float] = []
    _collect_numeric_values(
        order_payload,
        [
            "filledpct",
            "filled_pct",
            "fill_pct",
            "filledpercentage",
            "completion",
        ],
        pct_values,
    )

    for pct in pct_values:
        if 0 <= pct <= 1:
            return max(0.0, min(entry_size_tokens, pct * entry_size_tokens))
        if 1 < pct <= 100:
            return max(0.0, min(entry_size_tokens, (pct / 100.0) * entry_size_tokens))

    amount_values: List[float] = []
    _collect_numeric_values(
        order_payload,
        [
            "filled",
            "filledsize",
            "filled_size",
            "sizematched",
            "size_matched",
            "matchedsize",
            "matched_size",
            "filledamount",
            "filled_amount",
            "executedsize",
            "executed_size",
        ],
        amount_values,
    )

    best = 0.0
    for value in amount_values:
        val = value
        if val > entry_size_tokens * 1000:
            val = val / 1e6
        if val > best:
            best = val

    return max(0.0, min(entry_size_tokens, best))


class TpEngine:
    def __init__(self, store: InMemoryStore):
        self.store = store
        self._tasks: Dict[str, asyncio.Task] = {}

    def arm(self, session: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
        arm_id = f"tp_{uuid.uuid4().hex[:12]}"
        now = time.time()

        by_level = {
            int(item["level_index"]): {
                "order_type": item.get("order_type", "GTC"),
                "signed_order": item["signed_order"],
            }
            for item in payload["signed_tp_orders"]
        }

        state = {
            "arm_id": arm_id,
            "eoa_address": session["eoa_address"],
            "created_at": now,
            "updated_at": now,
            "entry_order_id": payload["entry_order_id"],
            "token_id": payload["token_id"],
            "entry_size_tokens": float(payload["entry_size_tokens"]),
            "mode": payload["mode"],
            "levels": [level.model_dump() if hasattr(level, "model_dump") else dict(level) for level in payload["levels"]],
            "signed_tp_orders": by_level,
            "placed_levels": {},
            "status": "armed",
            "last_filled_tokens": 0.0,
            "poll_seconds": float(TP_POLL_SECONDS),
            "max_minutes": int(payload.get("max_minutes") or TP_MAX_MINUTES),
            "events": [],
            "clob_creds": session["clob_creds"],
            "trading_context": session["trading_context"],
        }

        self.store.save_tp_arm(state)

        loop = asyncio.get_running_loop()
        task = loop.create_task(self._monitor_arm(arm_id), name=f"tp-monitor-{arm_id}")
        self._tasks[arm_id] = task

        return state

    async def _monitor_arm(self, arm_id: str) -> None:
        arm = self.store.get_tp_arm(arm_id)
        if not arm:
            return

        ctx = arm["trading_context"]
        client = Level2SessionClobClient(
            eoa_address=arm["eoa_address"],
            creds=arm["clob_creds"],
            funder_address=ctx.get("funder_address"),
            signature_type=int(ctx.get("signature_type") or 0),
        )

        created_at = float(arm["created_at"])
        deadline = created_at + int(arm["max_minutes"]) * 60

        while True:
            now = time.time()
            if now >= deadline:
                self.store.update_tp_arm(
                    arm_id,
                    {
                        "status": "timeout",
                        "updated_at": now,
                    },
                )
                self.store.append_tp_event(
                    arm_id,
                    {"ts": now, "event": "timeout", "message": "TP arm timed out"},
                )
                break

            arm = self.store.get_tp_arm(arm_id)
            if not arm:
                break
            if arm.get("status") in {"completed", "cancelled", "error", "timeout"}:
                break

            try:
                order_resp = client.get_order(arm["entry_order_id"])
                order_payload = order_resp.get("order") or {}
                filled_tokens = extract_filled_tokens(order_payload, float(arm["entry_size_tokens"]))

                self.store.update_tp_arm(
                    arm_id,
                    {
                        "last_filled_tokens": filled_tokens,
                        "updated_at": now,
                    },
                )

                fill_ratio = 0.0
                entry_size = float(arm["entry_size_tokens"])
                if entry_size > 0:
                    fill_ratio = max(0.0, min(1.0, filled_tokens / entry_size))

                cumulative = 0.0
                placed_levels = dict(arm.get("placed_levels") or {})

                for idx, level in enumerate(arm.get("levels") or []):
                    cumulative += float(level.get("size_pct", 0.0)) / 100.0
                    if fill_ratio + 1e-9 < cumulative:
                        continue
                    if str(idx) in placed_levels:
                        continue

                    signed_cfg = (arm.get("signed_tp_orders") or {}).get(idx)
                    if not signed_cfg:
                        placed_levels[str(idx)] = {
                            "status": "error",
                            "error": "Missing signed TP order for level",
                            "ts": now,
                        }
                        continue

                    sig = str((signed_cfg.get("signed_order") or {}).get("signature") or "")
                    idem = f"{arm_id}:{idx}:{sig}"
                    if not self.store.mark_idempotent(idem):
                        continue

                    post = client.post_signed_order(
                        signed_order=signed_cfg["signed_order"],
                        order_type=signed_cfg.get("order_type", "GTC"),
                    )

                    placed_levels[str(idx)] = {
                        "status": "placed",
                        "tp_order_id": post.get("order_id"),
                        "response": post.get("response"),
                        "fill_ratio_trigger": round(fill_ratio, 6),
                        "ts": now,
                    }

                    self.store.append_tp_event(
                        arm_id,
                        {
                            "ts": now,
                            "event": "tp_placed",
                            "level": idx,
                            "tp_order_id": post.get("order_id"),
                            "fill_ratio": round(fill_ratio, 6),
                        },
                    )

                done = len(placed_levels) >= len(arm.get("levels") or []) and len(arm.get("levels") or []) > 0
                status = "completed" if done else "armed"

                self.store.update_tp_arm(
                    arm_id,
                    {
                        "placed_levels": placed_levels,
                        "status": status,
                        "updated_at": now,
                    },
                )

                if done:
                    break

            except Exception as exc:
                self.store.append_tp_event(
                    arm_id,
                    {"ts": now, "event": "poll_error", "error": str(exc)},
                )

            await asyncio.sleep(float(arm.get("poll_seconds") or TP_POLL_SECONDS))

    def get_status(self, eoa_address: str, arm_id: Optional[str] = None) -> List[Dict[str, Any]]:
        if arm_id:
            arm = self.store.get_tp_arm(arm_id)
            if not arm:
                return []
            if (arm.get("eoa_address") or "").lower() != (eoa_address or "").lower():
                return []
            return [arm]

        return self.store.get_tp_arms_for_user(eoa_address)
