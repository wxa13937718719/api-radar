"""Conservative validation for prices and provider model identity."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any


def validate_price(value: Any, *, unit: str | None = None, field: str = "price") -> tuple[str, Decimal | None, str | None]:
    if value is None or value == "":
        return "unverified", None, f"{field} missing"
    try:
        price = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return "invalid", None, f"{field} is not numeric"
    if not price.is_finite() or price < 0:
        return "invalid", price, f"{field} must be a finite non-negative number"
    if unit is None or not str(unit).strip():
        return "unverified", price, "billing unit missing"
    # Sentinel values and accidental integer IDs should never become rankings.
    if price > Decimal(1000000):
        return "outlier", price, f"{field} exceeds plausibility bound"
    return "verified", price, None


def identity_status(provider_model_id: str, provider_model_name: str | None = None) -> str:
    value = str(provider_model_name or provider_model_id).strip()
    if not value:
        return "unresolved"
    # SiliconFlow's opaque numeric IDs are not model identities by themselves.
    if value.isdigit() or (value.startswith("sf-") and value[3:].isdigit()):
        return "unresolved"
    return "verified" if ("/" in value or any(char.isalpha() for char in value)) else "unresolved"


def eligible(*, validation: str, identity: str, provider_status: str, input_price: Decimal | None) -> bool:
    return (validation in {"verified", "partial"} and identity in {"verified", "mapped"}
            and provider_status in {"supported", "partially_supported"} and input_price is not None)
