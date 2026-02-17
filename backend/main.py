from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict, Optional

from eth_account import Account
from eth_account.messages import encode_typed_data
from py_clob_client.client import ClobClient
from py_clob_client.config import get_contract_config
from py_clob_client.clob_types import AssetType
from py_clob_client.exceptions import PolyApiException
from fastapi import Cookie, Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import auth
from .clob_session import Level2SessionClobClient
from .config import (
    AUTH_RATE_LIMIT_MAX_REQUESTS,
    AUTH_RATE_LIMIT_WINDOW_SECONDS,
    CHAIN_ID,
    CLOB_HOST,
    SESSION_COOKIE_NAME,
    WEB_EXPERIMENT_ENABLED,
)
from .models import (
    LimitOrderRequest,
    NonceRequest,
    NonceResponse,
    SearchResult,
    TpArmRequest,
    TpStatusResponse,
    VerifyRequest,
)
from .resolver import TradingContextResolver
from .store import InMemoryStore
from .tp_engine import TpEngine

if not WEB_EXPERIMENT_ENABLED:
    raise RuntimeError("WEB_EXPERIMENT is disabled. Set WEB_EXPERIMENT=1 to run this app.")

store = InMemoryStore()
resolver = TradingContextResolver()
tp_engine = TpEngine(store)
public_clob = ClobClient(host=CLOB_HOST, chain_id=CHAIN_ID)

app = FastAPI(title="OpiPoliX Web Experiment", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _enforce_auth_rate_limit(request: Request, bucket: str) -> None:
    ip = _client_ip(request)
    key = f"{bucket}:{ip}"
    allowed = store.allow_rate_limit(
        key=key,
        max_requests=AUTH_RATE_LIMIT_MAX_REQUESTS,
        window_seconds=AUTH_RATE_LIMIT_WINDOW_SECONDS,
    )
    if not allowed:
        raise HTTPException(status_code=429, detail="Too many auth attempts")


def _to_lower(value: Any) -> str:
    return str(value or "").lower()


def _normalize_side(raw: Any) -> str:
    if isinstance(raw, str):
        text = raw.upper().strip()
        if text in {"BUY", "SELL"}:
            return text
    try:
        n = int(raw)
        return "BUY" if n == 0 else "SELL"
    except Exception:
        pass
    raise HTTPException(status_code=400, detail="Invalid order side")


def _calc_order_size_tokens(signed_order: Dict[str, Any]) -> float:
    side = _normalize_side(signed_order.get("side"))
    maker_amount = float(signed_order.get("makerAmount") or 0)
    taker_amount = float(signed_order.get("takerAmount") or 0)
    if side == "BUY":
        return taker_amount / 1e6
    return maker_amount / 1e6


def _to_int_or_raise(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise HTTPException(status_code=400, detail=f"{field} must be integer-like")
    try:
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            text = value.strip()
            if text.startswith("0x") or text.startswith("0X"):
                return int(text, 16)
            return int(text)
        return int(value)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"{field} is invalid: {value!r}") from exc


def _order_side_to_uint8(value: Any) -> int:
    if isinstance(value, str):
        text = value.strip().upper()
        if text == "BUY":
            return 0
        if text == "SELL":
            return 1
    n = _to_int_or_raise(value, "side")
    if n in {0, 1}:
        return n
    raise HTTPException(status_code=400, detail=f"side must be BUY/SELL or 0/1, got {value!r}")


def _recover_order_signer_for_exchange(
    signed_order: Dict[str, Any],
    exchange_address: str,
) -> str:
    typed = {
        "types": {
            "EIP712Domain": [
                {"name": "name", "type": "string"},
                {"name": "version", "type": "string"},
                {"name": "chainId", "type": "uint256"},
                {"name": "verifyingContract", "type": "address"},
            ],
            "Order": [
                {"name": "salt", "type": "uint256"},
                {"name": "maker", "type": "address"},
                {"name": "signer", "type": "address"},
                {"name": "taker", "type": "address"},
                {"name": "tokenId", "type": "uint256"},
                {"name": "makerAmount", "type": "uint256"},
                {"name": "takerAmount", "type": "uint256"},
                {"name": "expiration", "type": "uint256"},
                {"name": "nonce", "type": "uint256"},
                {"name": "feeRateBps", "type": "uint256"},
                {"name": "side", "type": "uint8"},
                {"name": "signatureType", "type": "uint8"},
            ],
        },
        "primaryType": "Order",
        "domain": {
            "name": "Polymarket CTF Exchange",
            "version": "1",
            "chainId": int(CHAIN_ID),
            "verifyingContract": exchange_address,
        },
        "message": {
            "salt": _to_int_or_raise(signed_order.get("salt"), "salt"),
            "maker": str(signed_order.get("maker") or ""),
            "signer": str(signed_order.get("signer") or ""),
            "taker": str(signed_order.get("taker") or ""),
            "tokenId": _to_int_or_raise(signed_order.get("tokenId"), "tokenId"),
            "makerAmount": _to_int_or_raise(signed_order.get("makerAmount"), "makerAmount"),
            "takerAmount": _to_int_or_raise(signed_order.get("takerAmount"), "takerAmount"),
            "expiration": _to_int_or_raise(signed_order.get("expiration"), "expiration"),
            "nonce": _to_int_or_raise(signed_order.get("nonce"), "nonce"),
            "feeRateBps": _to_int_or_raise(signed_order.get("feeRateBps"), "feeRateBps"),
            "side": _order_side_to_uint8(signed_order.get("side")),
            "signatureType": _to_int_or_raise(signed_order.get("signatureType"), "signatureType"),
        },
    }
    signable = encode_typed_data(full_message=typed)
    signature = str(signed_order.get("signature") or "")
    if not signature:
        raise HTTPException(status_code=400, detail="signed_order.signature is missing")
    return Account.recover_message(signable, signature=signature)


def _recover_order_signer_candidates(signed_order: Dict[str, Any]) -> Dict[str, Optional[str]]:
    regular = get_contract_config(CHAIN_ID, False).exchange
    neg_risk = get_contract_config(CHAIN_ID, True).exchange
    out: Dict[str, Optional[str]] = {}
    for label, exchange in [("regular", regular), ("neg_risk", neg_risk)]:
        try:
            out[label] = _recover_order_signer_for_exchange(signed_order, exchange)
        except Exception:
            out[label] = None
    return out


def _poly_api_error_to_http(exc: PolyApiException, fallback_status: int = 400) -> HTTPException:
    status_raw = getattr(exc, "status_code", None)
    status_code = int(status_raw) if isinstance(status_raw, int) and status_raw > 0 else fallback_status
    status_code = max(400, min(status_code, 599))

    payload = getattr(exc, "error_msg", None)
    if isinstance(payload, dict):
        message = (
            str(payload.get("error") or "")
            or str(payload.get("message") or "")
            or str(payload)
        )
    else:
        message = str(payload or exc)

    if "Invalid order payload" in message:
        message += (
            ". Check token tradability, price tick-size, signatureType, and exchange contract "
            "(regular vs neg-risk)."
        )

    return HTTPException(status_code=status_code, detail=message)


def _validate_signed_order(
    signed_order: Dict[str, Any],
    session: Dict[str, Any],
    token_id: str,
    expected_side: str,
) -> None:
    context = session["trading_context"]
    expected_signer = _to_lower(session["eoa_address"])
    expected_maker = _to_lower(context.get("trading_address"))
    expected_sig_type = int(context.get("signature_type") or 0)

    signer = _to_lower(signed_order.get("signer"))
    maker = _to_lower(signed_order.get("maker"))

    if signer != expected_signer:
        raise HTTPException(status_code=400, detail="Signed order signer mismatch")

    if maker != expected_maker:
        raise HTTPException(status_code=400, detail="Signed order maker mismatch")

    order_sig_type = int(signed_order.get("signatureType"))
    if order_sig_type != expected_sig_type:
        raise HTTPException(status_code=400, detail="signatureType mismatch")

    if str(signed_order.get("tokenId")) != str(token_id):
        raise HTTPException(status_code=400, detail="tokenId mismatch")

    side = _normalize_side(signed_order.get("side"))
    if side != expected_side:
        raise HTTPException(status_code=400, detail=f"Expected {expected_side} order")


def _session_from_cookie(session_token: Optional[str] = Cookie(default=None, alias=SESSION_COOKIE_NAME)):
    if not session_token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    session = store.get_session(session_token)
    if not session:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    return session


@app.post("/api/auth/nonce", response_model=NonceResponse)
def create_nonce(payload: NonceRequest, request: Request):
    _enforce_auth_rate_limit(request, "nonce")

    address = auth.validate_eth_address(payload.address)
    message = auth.build_siwe_message(address=address, nonce="{nonce}", chain_id=CHAIN_ID)
    created = store.create_nonce(address=address, message=message)

    nonce = created["nonce"]
    message_with_nonce = message.replace("{nonce}", nonce)

    return NonceResponse(nonce=nonce, message=message_with_nonce, chain_id=CHAIN_ID)


@app.post("/api/auth/verify")
def verify_auth(payload: VerifyRequest, request: Request, response: Response):
    _enforce_auth_rate_limit(request, "verify")

    address = auth.validate_eth_address(payload.address)

    nonce_record = store.consume_nonce(address=address, nonce=payload.nonce)
    if not nonce_record:
        raise HTTPException(status_code=400, detail="Nonce is invalid or expired")

    expected_message = str(nonce_record["message"]).replace("{nonce}", payload.nonce)
    if payload.message != expected_message:
        raise HTTPException(status_code=400, detail="Signed message mismatch")

    recovered = auth.recover_personal_signer(payload.message, payload.signature)
    if recovered.lower() != address.lower():
        raise HTTPException(status_code=400, detail="SIWE signature address mismatch")

    auth.recover_clob_auth_signer(
        address=address,
        signature=payload.clob_auth_signature,
        timestamp=payload.clob_auth_timestamp,
        nonce=payload.clob_auth_nonce,
        chain_id=payload.chain_id,
    )

    clob_creds = auth.derive_clob_api_creds(
        address=address,
        signature=payload.clob_auth_signature,
        timestamp=payload.clob_auth_timestamp,
        nonce=payload.clob_auth_nonce,
    )

    context = resolver.resolve(address)
    session = store.create_session(
        eoa_address=address,
        clob_creds=clob_creds,
        trading_context=context,
    )

    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session["token"],
        httponly=True,
        secure=False,
        samesite="lax",
        max_age=int(session["expires_at"] - time.time()),
        path="/",
    )

    return {
        "ok": True,
        "eoa_address": session["eoa_address"],
        "trading_context": context,
    }


@app.get("/api/me")
def get_me(session: Dict[str, Any] = Depends(_session_from_cookie)):
    return {
        "eoa_address": session["eoa_address"],
        "trading_context": session["trading_context"],
    }


@app.get("/api/search", response_model=list[SearchResult])
def search_markets(
    query: str = Query(..., min_length=2, max_length=100),
    session: Dict[str, Any] = Depends(_session_from_cookie),
):
    _ = session
    return resolver.search(query, limit=20)


@app.get("/api/token/meta")
def get_token_meta(
    token_id: str = Query(..., min_length=10, max_length=200),
    session: Dict[str, Any] = Depends(_session_from_cookie),
):
    _ = session
    try:
        neg_risk = bool(public_clob.get_neg_risk(token_id))
        tick_size = str(public_clob.get_tick_size(token_id))
        fee_rate_bps = int(public_clob.get_fee_rate_bps(token_id) or 0)
        exchange_address = get_contract_config(CHAIN_ID, neg_risk).exchange
        min_order_size = None
        market = None
        best_bid = None
        best_ask = None
        try:
            book = public_clob.get_order_book(token_id)
            market = getattr(book, "market", None)
            min_order_size = str(getattr(book, "min_order_size", None) or "") or None
            bids = list(getattr(book, "bids", None) or [])
            asks = list(getattr(book, "asks", None) or [])
            if bids:
                best_bid = str(getattr(bids[0], "price", None) or "") or None
            if asks:
                best_ask = str(getattr(asks[0], "price", None) or "") or None
        except Exception:
            pass
        return {
            "token_id": str(token_id),
            "chain_id": CHAIN_ID,
            "neg_risk": neg_risk,
            "tick_size": tick_size,
            "fee_rate_bps": fee_rate_bps,
            "exchange_address": exchange_address,
            "market": market,
            "min_order_size": min_order_size,
            "best_bid": best_bid,
            "best_ask": best_ask,
        }
    except PolyApiException as exc:
        raise _poly_api_error_to_http(exc, fallback_status=400) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to load token metadata: {exc}") from exc


@app.get("/api/token/allowance")
def get_token_allowance(
    token_id: str = Query(..., min_length=10, max_length=200),
    session: Dict[str, Any] = Depends(_session_from_cookie),
):
    context = session["trading_context"]
    client = Level2SessionClobClient(
        eoa_address=session["eoa_address"],
        creds=session["clob_creds"],
        funder_address=context.get("funder_address"),
        signature_type=int(context.get("signature_type") or 0),
    )

    try:
        collateral = client.get_balance_allowance(asset_type=AssetType.COLLATERAL)
        conditional = client.get_balance_allowance(
            asset_type=AssetType.CONDITIONAL,
            token_id=token_id,
        )
        return {
            "token_id": str(token_id),
            "collateral": collateral.get("response"),
            "conditional": conditional.get("response"),
        }
    except PolyApiException as exc:
        raise _poly_api_error_to_http(exc, fallback_status=400) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Failed to load allowance: {exc}",
        ) from exc


@app.post("/api/order/limit")
def place_limit_order(
    payload: LimitOrderRequest,
    session: Dict[str, Any] = Depends(_session_from_cookie),
):
    if payload.idempotency_key and not store.mark_idempotent(payload.idempotency_key):
        return {"status": "duplicate", "detail": "idempotency_key already used"}

    _validate_signed_order(
        signed_order=payload.signed_order,
        session=session,
        token_id=payload.token_id,
        expected_side=payload.side,
    )

    recovered = _recover_order_signer_candidates(payload.signed_order)
    expected_signer = str(session["eoa_address"]).lower()
    rec_regular = str(recovered.get("regular") or "").lower()
    rec_neg_risk = str(recovered.get("neg_risk") or "").lower()
    if rec_regular != expected_signer and rec_neg_risk != expected_signer:
        raise HTTPException(
            status_code=400,
            detail=(
                "Order signature does not recover to authenticated EOA for either regular or "
                "neg-risk exchange contract."
            ),
        )

    context = session["trading_context"]
    client = Level2SessionClobClient(
        eoa_address=session["eoa_address"],
        creds=session["clob_creds"],
        funder_address=context.get("funder_address"),
        signature_type=int(context.get("signature_type") or 0),
    )

    print(
        "[WEB_EXPERIMENT] place_limit_attempt",
        {
            "eoa": session["eoa_address"],
            "maker": payload.signed_order.get("maker"),
            "signer": payload.signed_order.get("signer"),
            "token_id": payload.token_id,
            "side": payload.side,
            "price": payload.price,
            "order_type": payload.order_type,
            "signature_type": payload.signed_order.get("signatureType"),
            "salt": payload.signed_order.get("salt"),
            "nonce": payload.signed_order.get("nonce"),
            "maker_amount": payload.signed_order.get("makerAmount"),
            "taker_amount": payload.signed_order.get("takerAmount"),
            "fee_rate_bps": payload.signed_order.get("feeRateBps"),
            "salt_type": type(payload.signed_order.get("salt")).__name__,
            "nonce_type": type(payload.signed_order.get("nonce")).__name__,
            "token_id_type": type(payload.signed_order.get("tokenId")).__name__,
            "recovered_regular": recovered.get("regular"),
            "recovered_neg_risk": recovered.get("neg_risk"),
        },
    )

    try:
        result = client.post_signed_order(
            signed_order=payload.signed_order,
            order_type=payload.order_type,
        )
    except PolyApiException as exc:
        raise _poly_api_error_to_http(exc, fallback_status=400) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Failed to post order: {exc}") from exc

    order_id = result.get("order_id")
    entry_size_tokens = payload.size_tokens
    if entry_size_tokens is None:
        entry_size_tokens = _calc_order_size_tokens(payload.signed_order)

    print(
        "[WEB_EXPERIMENT] limit_order",
        {
            "eoa": session["eoa_address"],
            "trading_address": context.get("trading_address"),
            "token_id": payload.token_id,
            "side": payload.side,
            "price": payload.price,
            "order_id": order_id,
            "entry_size_tokens": entry_size_tokens,
        },
    )

    return {
        "status": "success",
        "order_id": order_id,
        "entry_size_tokens": entry_size_tokens,
        "raw": result.get("response"),
    }


@app.post("/api/tp/arm")
async def arm_tp(
    payload: TpArmRequest,
    session: Dict[str, Any] = Depends(_session_from_cookie),
):
    for item in payload.signed_tp_orders:
        _validate_signed_order(
            signed_order=item.signed_order,
            session=session,
            token_id=payload.token_id,
            expected_side="SELL",
        )

    arm_state = tp_engine.arm(session=session, payload=payload.model_dump())
    return {
        "status": "armed",
        "arm_id": arm_state["arm_id"],
        "entry_order_id": payload.entry_order_id,
    }


@app.get("/api/tp/status", response_model=TpStatusResponse)
def get_tp_status(
    arm_id: Optional[str] = Query(default=None),
    session: Dict[str, Any] = Depends(_session_from_cookie),
):
    arms = tp_engine.get_status(eoa_address=session["eoa_address"], arm_id=arm_id)
    return TpStatusResponse(arms=arms)


UI_DIR = Path(__file__).resolve().parents[1] / "ui"
app.mount("/", StaticFiles(directory=str(UI_DIR), html=True), name="ui")
