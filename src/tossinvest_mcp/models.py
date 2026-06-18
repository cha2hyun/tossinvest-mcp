from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Symbol = str
Currency = Literal["KRW", "USD"]
OrderSide = Literal["BUY", "SELL"]
OrderType = Literal["LIMIT", "MARKET"]
TimeInForce = Literal["DAY", "CLS"]


class OrderPreviewRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    symbol: Symbol = Field(pattern=r"^[A-Za-z0-9.\-]+$")
    side: OrderSide
    order_type: OrderType
    quantity: str | None = Field(default=None, pattern=r"^\d+$")
    price: str | None = Field(default=None, pattern=r"^\d+(\.\d+)?$")
    order_amount: str | None = Field(default=None, pattern=r"^\d+(\.\d+)?$")
    time_in_force: TimeInForce = "DAY"

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

    order_id: str = Field(min_length=1)
    order_type: OrderType
    quantity: str | None = Field(default=None, pattern=r"^\d+$")
    price: str | None = Field(default=None, pattern=r"^\d+(\.\d+)?$")

    @model_validator(mode="after")
    def validate_shape(self) -> OrderModificationRequest:
        if self.order_type == "LIMIT" and self.price is None:
            raise ValueError("price is required for LIMIT modifications")
        if self.order_type == "MARKET" and self.price is not None:
            raise ValueError("price is not allowed for MARKET modifications")
        return self

    def to_api_payload(self) -> dict[str, str]:
        payload: dict[str, str] = {"orderType": self.order_type}
        if self.quantity is not None:
            payload["quantity"] = self.quantity
        if self.price is not None:
            payload["price"] = self.price
        return payload
