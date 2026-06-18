from __future__ import annotations

from typing import Any


class TossInvestError(RuntimeError):
    """A normalized error returned by the Toss Securities Open API."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        code: str = "upstream-error",
        request_id: str | None = None,
        data: Any = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.request_id = request_id
        self.data = data

    def as_dict(self) -> dict[str, Any]:
        return {
            "error": {
                "status_code": self.status_code,
                "code": self.code,
                "message": str(self),
                "request_id": self.request_id,
                "data": self.data,
            }
        }


class OrderStateUnknownError(TossInvestError):
    """A write request failed after dispatch and must not be retried automatically."""

    def __init__(self, message: str) -> None:
        super().__init__(
            message,
            code="order-state-unknown",
            data={
                "retry": False,
                "guidance": "Do not repeat the order automatically. Check the order list first.",
            },
        )
