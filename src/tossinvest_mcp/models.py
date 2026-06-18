from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal, NotRequired, TypedDict

from pydantic import BaseModel, ConfigDict, Field, model_validator

Symbol = str
Currency = Literal["KRW", "USD"]
OrderSide = Literal["BUY", "SELL"]
OrderType = Literal["LIMIT", "MARKET"]
TimeInForce = Literal["DAY", "CLS"]


class RateLimitMetadata(TypedDict, total=False):
    limit: str | None
    remaining: str | None
    reset: str | None


class ResponseMetadata(TypedDict, total=False):
    request_id: str | None
    retrieved_at: str
    rate_limit: RateLimitMetadata


class ApiResponse(TypedDict):
    data: Any
    meta: ResponseMetadata


class PreviewResponse(TypedDict):
    preview_id: str
    expires_in_seconds: int
    expires_at: str
    approval_url: str
    summary: dict[str, Any]
    status: Literal["pending_human_approval"]
    warning: str


class OrderExecutionResponse(TypedDict):
    operation: ApiResponse
    order: ApiResponse | None
    warning: NotRequired[str]
    order_lookup_error: NotRequired[dict[str, Any]]


class OrderPreviewRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    symbol: Symbol = Field(
        pattern=r"^[A-Za-z0-9.\-]+$",
        description="KRX 6-digit symbol or US ticker.",
    )
    side: OrderSide = Field(description="BUY or SELL.")
    order_type: OrderType = Field(description="LIMIT or MARKET.")
    quantity: str | None = Field(
        default=None,
        pattern=r"^\d+$",
        max_length=30,
        description="Whole-share quantity. Provide exactly one of quantity or order_amount.",
    )
    price: str | None = Field(
        default=None,
        pattern=r"^\d+(\.\d+)?$",
        max_length=30,
        description="Required for LIMIT and forbidden for MARKET.",
    )
    order_amount: str | None = Field(
        default=None,
        pattern=r"^\d+(\.\d+)?$",
        max_length=30,
        description="Fixed USD amount for US MARKET orders only.",
    )
    time_in_force: TimeInForce = Field(
        default="DAY",
        description="DAY, or CLS for US LIMIT orders only.",
    )

    @model_validator(mode="after")
    def validate_shape(self) -> OrderPreviewRequest:
        quantity_based = self.quantity is not None
        amount_based = self.order_amount is not None
        if quantity_based == amount_based:
            raise ValueError("Provide exactly one of quantity or order_amount")
        if self.order_type == "LIMIT" and self.price is None:
            raise ValueError("price is required for LIMIT orders")
        if self.order_type == "MARKET" and self.price is not None:
            raise ValueError("price is not allowed for MARKET orders")
        if amount_based and self.order_type != "MARKET":
            raise ValueError("Amount-based orders support MARKET orders only")
        if amount_based and self.time_in_force != "DAY":
            raise ValueError("Amount-based orders do not support a custom time_in_force")
        if self.time_in_force == "CLS" and self.order_type != "LIMIT":
            raise ValueError("CLS is supported only with LIMIT orders")
        if self.quantity is not None and Decimal(self.quantity) <= 0:
            raise ValueError("quantity must be greater than zero")
        if self.price is not None and Decimal(self.price) <= 0:
            raise ValueError("price must be greater than zero")
        if self.order_amount is not None and Decimal(self.order_amount) <= 0:
            raise ValueError("order_amount must be greater than zero")
        return self

    def estimated_amount(self, market_price: Decimal | None = None) -> Decimal:
        if self.order_amount is not None:
            return Decimal(self.order_amount)
        price = Decimal(self.price) if self.price is not None else market_price
        if price is None or self.quantity is None:
            raise ValueError("A market price is required to estimate a quantity-based market order")
        return price * Decimal(self.quantity)

    def to_api_payload(self, client_order_id: str) -> dict[str, object]:
        payload: dict[str, object] = {
            "clientOrderId": client_order_id,
            "symbol": self.symbol,
            "side": self.side,
            "orderType": self.order_type,
        }
        if self.quantity is not None:
            payload["quantity"] = self.quantity
        if self.price is not None:
            payload["price"] = self.price
        if self.order_amount is not None:
            payload["orderAmount"] = self.order_amount
        if self.time_in_force != "DAY":
            payload["timeInForce"] = self.time_in_force
        return payload


class OrderModificationRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    order_id: str = Field(
        min_length=1,
        max_length=256,
        description="Existing Toss Securities order ID.",
    )
    order_type: OrderType = Field(description="Replacement LIMIT or MARKET order type.")
    quantity: str | None = Field(
        default=None,
        pattern=r"^\d+$",
        max_length=30,
        description="Required for KR modifications and forbidden for US modifications.",
    )
    price: str | None = Field(
        default=None,
        pattern=r"^\d+(\.\d+)?$",
        max_length=30,
        description="Required for LIMIT and forbidden for MARKET.",
    )

    @model_validator(mode="after")
    def validate_shape(self) -> OrderModificationRequest:
        if self.order_type == "LIMIT" and self.price is None:
            raise ValueError("price is required for LIMIT modifications")
        if self.order_type == "MARKET" and self.price is not None:
            raise ValueError("price is not allowed for MARKET modifications")
        if self.quantity is not None and Decimal(self.quantity) <= 0:
            raise ValueError("quantity must be greater than zero")
        if self.price is not None and Decimal(self.price) <= 0:
            raise ValueError("price must be greater than zero")
        return self

    def to_api_payload(self) -> dict[str, str]:
        payload: dict[str, str] = {"orderType": self.order_type}
        if self.quantity is not None:
            payload["quantity"] = self.quantity
        if self.price is not None:
            payload["price"] = self.price
        return payload
