from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Awaitable, Callable, Optional, Protocol


class OrderStatus(str, Enum):
    created = "created"
    paid = "paid"
    completed = "completed"
    rejected = "rejected"
    expired = "expired"


class CapEvent(str, Enum):
    NEGOTIATION_CREATED = "NEGOTIATION_CREATED"
    NEGOTIATION_REJECTED = "NEGOTIATION_REJECTED"
    NEGOTIATION_EXPIRED = "NEGOTIATION_EXPIRED"
    ORDER_CREATED = "ORDER_CREATED"
    ORDER_PAID = "ORDER_PAID"
    ORDER_COMPLETED = "ORDER_COMPLETED"
    ORDER_REJECTED = "ORDER_REJECTED"
    ORDER_EXPIRED = "ORDER_EXPIRED"


@dataclass
class Negotiation:
    negotiation_id: str
    service_id: str
    requester_did: str
    requirements: dict


@dataclass
class Order:
    order_id: str
    service_id: str
    status: OrderStatus
    price_usdc: float
    requirements: dict
    negotiation_id: Optional[str] = None


@dataclass
class Delivery:
    order_id: str
    deliverable: dict
    file_url: Optional[str] = None


class CapError(Exception):
    def __init__(self, message: str, code: Optional[str] = None):
        super().__init__(message)
        self.code = code


def is_insufficient_balance(e: Exception) -> bool:
    return isinstance(e, CapError) and e.code == "insufficient_balance"


def is_invalid_status(e: Exception) -> bool:
    return isinstance(e, CapError) and e.code == "invalid_status"


def is_not_found(e: Exception) -> bool:
    return isinstance(e, CapError) and e.code == "not_found"


Handler = Callable[[object], Awaitable[None]]


class CapClient(Protocol):
    # lifecycle
    async def connect(self) -> None: ...
    async def close(self) -> None: ...
    async def run_forever(self) -> None: ...
    def on(self, event: CapEvent, handler: Handler) -> None: ...
    # requester
    async def negotiate_order(self, service_id: str, requirements: dict) -> Negotiation: ...
    async def await_order_created(self, negotiation_id: str, timeout: float) -> Order: ...
    async def pay_order(self, order_id: str) -> None: ...
    async def await_completion(self, order_id: str, timeout: float) -> Order: ...
    async def get_delivery(self, order_id: str) -> Delivery: ...
    async def get_download_url(self, file_id: str) -> str: ...
    # provider
    async def get_negotiation(self, negotiation_id: str) -> Negotiation: ...
    async def accept_negotiation(self, negotiation_id: str,
                                 fund_address: Optional[str] = None) -> Order: ...
    async def reject_negotiation(self, negotiation_id: str, reason: str = "") -> None: ...
    async def deliver_order(self, order_id: str, deliverable: dict,
                            file_url: Optional[str] = None) -> None: ...
    async def reject_order(self, order_id: str, reason: str = "") -> None: ...
    async def upload_file(self, content: bytes, filename: str) -> str: ...
    # both
    async def get_order(self, order_id: str) -> Order: ...
    async def list_orders(self) -> list[Order]: ...
    async def list_negotiations(self) -> list[Negotiation]: ...
    async def get_balance(self, address: Optional[str] = None) -> float: ...
