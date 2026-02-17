from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


class NonceRequest(BaseModel):
    address: str = Field(..., min_length=42, max_length=42)


class NonceResponse(BaseModel):
    nonce: str
    message: str
    chain_id: int


class VerifyRequest(BaseModel):
    address: str = Field(..., min_length=42, max_length=42)
    nonce: str = Field(..., min_length=8)
    message: str = Field(..., min_length=20)
    signature: str = Field(..., min_length=10)
    chain_id: int = 137

    clob_auth_signature: str = Field(..., min_length=10)
    clob_auth_timestamp: int
    clob_auth_nonce: int


class SearchResult(BaseModel):
    market_id: str
    title: str
    question: Optional[str] = None
    liquidity: float = 0.0
    opportunity_score: float = 0.0
    yes_token_id: Optional[str] = None
    no_token_id: Optional[str] = None
    yes_label: Optional[str] = None
    no_label: Optional[str] = None
    source: str = "dome"


class LimitOrderRequest(BaseModel):
    token_id: str = Field(..., min_length=10)
    side: Literal["BUY", "SELL"]
    outcome: Optional[Literal["YES", "NO"]] = None
    price: float = Field(..., gt=0, lt=1)
    size_usdc: Optional[float] = Field(default=None, gt=0)
    size_tokens: Optional[float] = Field(default=None, gt=0)
    order_type: Literal["GTC", "GTD", "FOK", "FAK"] = "GTC"
    idempotency_key: Optional[str] = None
    signed_order: Optional[Dict[str, Any]] = None

    @field_validator("signed_order")
    @classmethod
    def validate_signed_order(cls, value: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if value is None:
            return value
        required = [
            "salt",
            "maker",
            "signer",
            "taker",
            "tokenId",
            "makerAmount",
            "takerAmount",
            "expiration",
            "nonce",
            "feeRateBps",
            "side",
            "signatureType",
            "signature",
        ]
        missing = [k for k in required if k not in value]
        if missing:
            raise ValueError(f"signed_order missing fields: {', '.join(missing)}")
        return value


class CancelOrderRequest(BaseModel):
    order_id: str = Field(..., min_length=6, max_length=200)


class TpLevel(BaseModel):
    price: float = Field(..., gt=0, lt=1)
    size_pct: float = Field(..., gt=0, le=100)


class SignedTpOrder(BaseModel):
    level_index: int = Field(..., ge=0, le=9)
    order_type: Literal["GTC", "GTD", "FOK", "FAK"] = "GTC"
    signed_order: Dict[str, Any]


class TpArmRequest(BaseModel):
    entry_order_id: str = Field(..., min_length=4)
    token_id: str = Field(..., min_length=10)
    entry_size_tokens: float = Field(..., gt=0)
    mode: Literal["single", "ladder"]
    levels: List[TpLevel] = Field(..., min_length=1, max_length=3)
    signed_tp_orders: List[SignedTpOrder] = Field(..., min_length=1, max_length=3)
    max_minutes: Optional[int] = Field(default=None, ge=1, le=180)

    @field_validator("levels")
    @classmethod
    def validate_levels_sum(cls, levels: List[TpLevel]) -> List[TpLevel]:
        total = sum(level.size_pct for level in levels)
        if abs(total - 100.0) > 0.2:
            raise ValueError("TP level percentages must sum to 100")
        return levels


class TpStatusResponse(BaseModel):
    arms: List[Dict[str, Any]]
