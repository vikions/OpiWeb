from __future__ import annotations

import secrets
import threading
import time
from collections import defaultdict
from typing import Any, Dict, List, Optional

from .config import NONCE_TTL_SECONDS, SESSION_TTL_SECONDS


class InMemoryStore:
    def __init__(self):
        self._lock = threading.RLock()

        self._nonces: Dict[str, Dict[str, Any]] = {}
        self._sessions: Dict[str, Dict[str, Any]] = {}
        self._rate_limits: Dict[str, List[float]] = defaultdict(list)

        self._tp_arms: Dict[str, Dict[str, Any]] = {}
        self._idempotency_keys: set[str] = set()

    def create_nonce(self, address: str, message: str) -> Dict[str, Any]:
        nonce = secrets.token_hex(16)
        now = time.time()
        with self._lock:
            self._nonces[address.lower()] = {
                "nonce": nonce,
                "message": message,
                "created_at": now,
                "expires_at": now + NONCE_TTL_SECONDS,
            }
        return {"nonce": nonce, "message": message}

    def consume_nonce(self, address: str, nonce: str) -> Optional[Dict[str, Any]]:
        key = address.lower()
        with self._lock:
            record = self._nonces.get(key)
            if not record:
                return None
            if record["expires_at"] < time.time():
                self._nonces.pop(key, None)
                return None
            if record["nonce"] != nonce:
                return None
            self._nonces.pop(key, None)
            return record

    def create_session(
        self,
        eoa_address: str,
        clob_creds: Dict[str, str],
        trading_context: Dict[str, Any],
    ) -> Dict[str, Any]:
        token = secrets.token_urlsafe(48)
        now = time.time()
        session = {
            "token": token,
            "eoa_address": eoa_address,
            "clob_creds": clob_creds,
            "trading_context": trading_context,
            "created_at": now,
            "expires_at": now + SESSION_TTL_SECONDS,
        }
        with self._lock:
            self._sessions[token] = session
        return session

    def get_session(self, token: str) -> Optional[Dict[str, Any]]:
        if not token:
            return None

        with self._lock:
            session = self._sessions.get(token)
            if not session:
                return None
            if session["expires_at"] < time.time():
                self._sessions.pop(token, None)
                return None
            return session

    def delete_session(self, token: str) -> None:
        with self._lock:
            self._sessions.pop(token, None)

    def allow_rate_limit(self, key: str, max_requests: int, window_seconds: int) -> bool:
        now = time.time()
        floor = now - window_seconds
        with self._lock:
            entries = [ts for ts in self._rate_limits.get(key, []) if ts >= floor]
            if len(entries) >= max_requests:
                self._rate_limits[key] = entries
                return False
            entries.append(now)
            self._rate_limits[key] = entries
            return True

    def save_tp_arm(self, state: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            self._tp_arms[state["arm_id"]] = state
        return state

    def get_tp_arm(self, arm_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            arm = self._tp_arms.get(arm_id)
            if arm is None:
                return None
            return dict(arm)

    def update_tp_arm(self, arm_id: str, patch: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        with self._lock:
            arm = self._tp_arms.get(arm_id)
            if arm is None:
                return None
            arm.update(patch)
            self._tp_arms[arm_id] = arm
            return dict(arm)

    def append_tp_event(self, arm_id: str, event: Dict[str, Any]) -> None:
        with self._lock:
            arm = self._tp_arms.get(arm_id)
            if arm is None:
                return
            events = arm.setdefault("events", [])
            events.append(event)
            self._tp_arms[arm_id] = arm

    def get_tp_arms_for_user(self, eoa_address: str) -> List[Dict[str, Any]]:
        target = (eoa_address or "").lower()
        with self._lock:
            return [
                dict(arm)
                for arm in self._tp_arms.values()
                if (arm.get("eoa_address") or "").lower() == target
            ]

    def mark_idempotent(self, key: str) -> bool:
        with self._lock:
            if key in self._idempotency_keys:
                return False
            self._idempotency_keys.add(key)
            return True
