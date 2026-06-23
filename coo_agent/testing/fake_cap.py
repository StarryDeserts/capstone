from __future__ import annotations

import asyncio
import itertools
from dataclasses import dataclass
from typing import Optional

from ..cap_client import (
    CapError, CapEvent, Delivery, Handler, Negotiation, Order, OrderStatus,
)

_ids = itertools.count(1)


@dataclass
class Fault:
    reject_negotiation: bool = False
    silent_on_pay: bool = False


class FakeExchange:
    def __init__(self, fee_rate: float = 0.0):
        self.fee_rate = fee_rate
        self.clients: dict[str, "FakeCapClient"] = {}
        self.providers: dict[str, "FakeCapClient"] = {}
        self.price_by_service: dict[str, float] = {}
        self.negotiations: dict[str, Negotiation] = {}
        self.orders: dict[str, Order] = {}
        self.deliveries: dict[str, Delivery] = {}
        self.balances: dict[str, float] = {}
        self.escrow: dict[str, float] = {}
        self.requester_by_order: dict[str, str] = {}
        self.requester_by_neg: dict[str, str] = {}

    def credit(self, agent_id: str, amount: float) -> None:
        self.balances[agent_id] = self.balances.get(agent_id, 0.0) + amount

    def register_service(self, service_id: str, provider: "FakeCapClient", price: float) -> None:
        self.providers[service_id] = provider
        self.price_by_service[service_id] = price

    async def expire_order(self, order_id: str) -> None:
        order = self.orders.get(order_id)
        if order is None or order.status is not OrderStatus.paid:
            return
        order.status = OrderStatus.expired
        amount = self.escrow.pop(order_id, 0.0)
        requester = self.requester_by_order[order_id]
        self.credit(requester, amount)
        self.clients[requester]._push(CapEvent.ORDER_EXPIRED, order)


class FakeCapClient:
    def __init__(self, exchange: FakeExchange, agent_id: str,
                 serves: list[tuple[str, float]] = (), fault: Optional[Fault] = None):
        self.ex = exchange
        self.agent_id = agent_id
        self.fault = fault or Fault()
        self._handlers: dict[CapEvent, list[Handler]] = {}
        self._ready: dict[tuple, tuple] = {}
        self._waiters: dict[tuple, asyncio.Future] = {}
        exchange.clients[agent_id] = self
        for service_id, price in serves:
            exchange.register_service(service_id, self, price)

    # ---- lifecycle ----
    async def connect(self) -> None: ...
    async def close(self) -> None: ...
    async def run_forever(self) -> None:
        await asyncio.Event().wait()  # block; tests don't call this

    def on(self, event: CapEvent, handler: Handler) -> None:
        self._handlers.setdefault(event, []).append(handler)

    # ---- internal delivery ----
    async def _dispatch(self, event: CapEvent, payload) -> None:
        for handler in list(self._handlers.get(event, [])):
            await handler(payload)

    @staticmethod
    def _key(event: CapEvent, payload) -> tuple:
        if event in (CapEvent.ORDER_CREATED, CapEvent.NEGOTIATION_REJECTED,
                     CapEvent.NEGOTIATION_EXPIRED):
            nid = getattr(payload, "negotiation_id", None)
            return ("neg", nid)
        return ("order", payload.order_id)

    def _push(self, event: CapEvent, payload) -> None:
        key = self._key(event, payload)
        fut = self._waiters.pop(key, None)
        if fut is not None and not fut.done():
            fut.set_result((event, payload))
        else:
            self._ready[key] = (event, payload)

    async def _wait_key(self, key: tuple, timeout: float) -> tuple:
        if key in self._ready:
            return self._ready.pop(key)
        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        self._waiters[key] = fut
        try:
            return await asyncio.wait_for(fut, timeout)
        except asyncio.TimeoutError as exc:
            self._waiters.pop(key, None)
            raise CapError("timeout", code="timeout") from exc

    # ---- requester ----
    async def negotiate_order(self, service_id: str, requirements: dict) -> Negotiation:
        provider = self.ex.providers.get(service_id)
        if provider is None:
            raise CapError(f"no service {service_id}", code="not_found")
        nid = f"neg_{next(_ids)}"
        neg = Negotiation(nid, service_id, requester_did=self.agent_id, requirements=requirements)
        self.ex.negotiations[nid] = neg
        self.ex.requester_by_neg[nid] = self.agent_id
        if provider.fault.reject_negotiation:
            self._push(CapEvent.NEGOTIATION_REJECTED, neg)
        else:
            await provider._dispatch(CapEvent.NEGOTIATION_CREATED, neg)
        return neg

    async def await_order_created(self, negotiation_id: str, timeout: float) -> Order:
        event, payload = await self._wait_key(("neg", negotiation_id), timeout)
        if event is CapEvent.ORDER_CREATED:
            return payload
        raise CapError("negotiation rejected", code="rejected")

    async def pay_order(self, order_id: str) -> None:
        order = self.ex.orders[order_id]
        if order.status is not OrderStatus.created:
            raise CapError("not payable", code="invalid_status")
        price = order.price_usdc
        if self.ex.balances.get(self.agent_id, 0.0) < price:
            raise CapError("insufficient balance", code="insufficient_balance")
        self.ex.balances[self.agent_id] -= price
        self.ex.escrow[order_id] = price
        order.status = OrderStatus.paid
        provider = self.ex.providers[order.service_id]
        if not provider.fault.silent_on_pay:
            await provider._dispatch(CapEvent.ORDER_PAID, order)

    async def await_completion(self, order_id: str, timeout: float) -> Order:
        try:
            _event, payload = await self._wait_key(("order", order_id), timeout)
            return payload
        except CapError as exc:
            if exc.code == "timeout":
                await self.ex.expire_order(order_id)
            raise

    async def get_delivery(self, order_id: str) -> Delivery:
        d = self.ex.deliveries.get(order_id)
        if d is None:
            raise CapError("no delivery", code="not_found")
        return d

    async def get_download_url(self, file_id: str) -> str:
        return f"fake://file/{file_id}"

    # ---- provider ----
    async def get_negotiation(self, negotiation_id: str) -> Negotiation:
        return self.ex.negotiations[negotiation_id]

    async def accept_negotiation(self, negotiation_id: str,
                                 fund_address: Optional[str] = None) -> Order:
        neg = self.ex.negotiations[negotiation_id]
        oid = f"ord_{next(_ids)}"
        order = Order(oid, neg.service_id, OrderStatus.created,
                      self.ex.price_by_service[neg.service_id], neg.requirements, negotiation_id)
        self.ex.orders[oid] = order
        requester = self.ex.requester_by_neg[negotiation_id]
        self.ex.requester_by_order[oid] = requester
        self.ex.clients[requester]._push(CapEvent.ORDER_CREATED, order)
        return order

    async def reject_negotiation(self, negotiation_id: str, reason: str = "") -> None:
        neg = self.ex.negotiations[negotiation_id]
        requester = self.ex.requester_by_neg[negotiation_id]
        self.ex.clients[requester]._push(CapEvent.NEGOTIATION_REJECTED, neg)

    async def deliver_order(self, order_id: str, deliverable: dict,
                            file_url: Optional[str] = None) -> None:
        order = self.ex.orders[order_id]
        if order.status is not OrderStatus.paid:
            raise CapError("not deliverable", code="invalid_status")
        order.status = OrderStatus.completed
        self.ex.deliveries[order_id] = Delivery(order_id, deliverable, file_url)
        amount = self.ex.escrow.pop(order_id, 0.0)
        self.ex.credit(self.agent_id, amount * (1.0 - self.ex.fee_rate))
        requester = self.ex.requester_by_order[order_id]
        self.ex.clients[requester]._push(CapEvent.ORDER_COMPLETED, order)

    async def reject_order(self, order_id: str, reason: str = "") -> None:
        order = self.ex.orders[order_id]
        order.status = OrderStatus.rejected
        amount = self.ex.escrow.pop(order_id, 0.0)
        requester = self.ex.requester_by_order[order_id]
        self.ex.credit(requester, amount)
        self.ex.clients[requester]._push(CapEvent.ORDER_REJECTED, order)

    async def upload_file(self, content: bytes, filename: str) -> str:
        return f"fake://upload/{filename}"

    # ---- both ----
    async def get_order(self, order_id: str) -> Order:
        return self.ex.orders[order_id]

    async def list_orders(self) -> list[Order]:
        return list(self.ex.orders.values())

    async def list_negotiations(self) -> list[Negotiation]:
        return list(self.ex.negotiations.values())

    async def get_balance(self, address: Optional[str] = None) -> float:
        return self.ex.balances.get(self.agent_id, 0.0)
