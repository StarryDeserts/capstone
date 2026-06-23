from dataclasses import dataclass
from typing import Optional

from .cap_client import CapClient, CapError, OrderStatus


@dataclass
class HireResult:
    ok: bool
    deliverable: Optional[dict]
    order_id: Optional[str]
    price_usdc: float
    service_id: str
    status: str
    error: Optional[str] = None


async def hire(cap: CapClient, service_id: str, requirements: dict, *,
               timeout: float) -> HireResult:
    order_id: Optional[str] = None
    price = 0.0
    try:
        neg = await cap.negotiate_order(service_id, requirements)
        order = await cap.await_order_created(neg.negotiation_id, timeout=timeout)
        order_id = order.order_id
        price = order.price_usdc
        await cap.pay_order(order.order_id)
        completed = await cap.await_completion(order.order_id, timeout=timeout)
        if completed.status is not OrderStatus.completed:
            return HireResult(False, None, order_id, price, service_id,
                              completed.status.value,
                              f"order {completed.status.value}")
        delivery = await cap.get_delivery(order.order_id)
        return HireResult(True, delivery.deliverable, order_id, price,
                          service_id, completed.status.value)
    except CapError as exc:
        return HireResult(False, None, order_id, price, service_id,
                          exc.code or "error", str(exc))
