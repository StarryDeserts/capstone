from __future__ import annotations

import asyncio
import json
from typing import Awaitable, Callable, Optional

from .cap_client import (CapError, CapEvent, Delivery, Negotiation, Order,
                         OrderStatus)

Handler = Callable[[object], Awaitable[None]]

_TERMINAL = (CapEvent.ORDER_COMPLETED, CapEvent.ORDER_REJECTED,
             CapEvent.ORDER_EXPIRED)

# Real croo EventType wire strings -> our CapEvent. _to_event ALSO accepts the
# CapEvent member NAMES (e.g. "ORDER_CREATED") so the unit tests can drive
# _dispatch directly without constructing croo Events.
_WIRE_TO_EVENT = {
    "order_negotiation_created": CapEvent.NEGOTIATION_CREATED,
    "order_negotiation_rejected": CapEvent.NEGOTIATION_REJECTED,
    "order_negotiation_expired": CapEvent.NEGOTIATION_EXPIRED,
    "order_created": CapEvent.ORDER_CREATED,
    "order_paid": CapEvent.ORDER_PAID,
    "order_completed": CapEvent.ORDER_COMPLETED,
    "order_rejected": CapEvent.ORDER_REJECTED,
    "order_expired": CapEvent.ORDER_EXPIRED,
}

# croo OrderStatus wire strings (incl. transient/failure) -> our coarse enum.
# Transient in-flight states fold to the nearest stable state; *_failed -> rejected
# (a failure must NOT read as success to hire()/the orchestrator failover).
_STATUS_MAP = {
    "created": OrderStatus.created, "creating": OrderStatus.created,
    "paid": OrderStatus.paid, "paying": OrderStatus.paid,
    "completed": OrderStatus.completed,
    "rejected": OrderStatus.rejected, "rejecting": OrderStatus.rejected,
    "expired": OrderStatus.expired,
    "create_failed": OrderStatus.rejected,
    "pay_failed": OrderStatus.rejected,
    "deliver_failed": OrderStatus.rejected,
}


def _g(obj, *names, default=None):
    """First present, non-None field from a dict OR object (SDK shape varies)."""
    for n in names:
        if isinstance(obj, dict):
            if obj.get(n) is not None:
                return obj[n]
        else:
            v = getattr(obj, n, None)
            if v is not None:
                return v
    return default


def _loads(v) -> dict:
    """croo carries requirements/deliverable as JSON strings; tests pass dicts."""
    if isinstance(v, dict):
        return v
    if isinstance(v, str) and v:
        try:
            out = json.loads(v)
        except (ValueError, TypeError):
            return {}
        return out if isinstance(out, dict) else {"value": out}
    return {}


def _status(raw) -> OrderStatus:
    return _STATUS_MAP.get(str(raw).lower(), OrderStatus.created)


class RealCapClient:
    """CapClient Protocol implemented over the real `croo` SDK.

    See docs/superpowers/notes/cap-sdk-interface.md for the SDK surface. croo
    imports are lazy so this module imports even where croo is absent; the
    injected `sdk=` fake bypasses them in tests.
    """

    def __init__(self, sk_key: str, api_url: str, ws_url: str,
                 rpc_url: Optional[str] = None, *, sdk=None,
                 balance_fn: Optional[Callable[[Optional[str]], Awaitable[float]]] = None):
        self._sk = sk_key
        self._api_url = api_url
        self._ws_url = ws_url
        self._rpc_url = rpc_url
        self._sdk = sdk
        self._balance_fn = balance_fn
        self._stream = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._closed = asyncio.Event()
        self._handlers: dict[CapEvent, list[Handler]] = {}
        self._created_ready: dict[str, Order] = {}
        self._created_waiters: dict[str, asyncio.Future] = {}
        self._created_errors: dict[str, CapError] = {}
        self._done_ready: dict[str, Order] = {}
        self._done_waiters: dict[str, asyncio.Future] = {}
        self._req_by_order: dict[str, dict] = {}  # backfill provider requirements
        self._tasks: set = set()

    # --- translation (single reconciliation point vs Task 18 notes) -------
    def _neg_from(self, p) -> Negotiation:
        return Negotiation(
            negotiation_id=_g(p, "negotiation_id", "negotiationId", "id", default=""),
            service_id=_g(p, "service_id", "serviceId", default=""),
            requester_did=_g(p, "requester_did", "requester_agent_id",
                             "requesterAgentId", default=""),
            requirements=_loads(_g(p, "requirements", default={})))

    def _order_from(self, p) -> Order:
        oid = _g(p, "order_id", "orderId", "id", default="")
        reqs = self._req_by_order.get(oid) or _loads(_g(p, "requirements", default={}))
        return Order(
            order_id=oid,
            service_id=_g(p, "service_id", "serviceId", default=""),
            status=_status(_g(p, "status", default="created")),
            price_usdc=float(_g(p, "price", "price_usdc", "priceUsdc", default=0.0) or 0.0),
            requirements=reqs,
            negotiation_id=_g(p, "negotiation_id", "negotiationId"))

    def _delivery_from(self, order_id, p) -> Delivery:
        return Delivery(
            order_id=order_id,
            deliverable=_loads(_g(p, "deliverable_text", "deliverable", default={})),
            file_url=_g(p, "file_url", "fileUrl"))

    # --- lifecycle --------------------------------------------------------
    def _build_sdk(self):
        from croo import AgentClient, Config
        return AgentClient(
            Config(base_url=self._api_url, ws_url=self._ws_url,
                   rpc_url=self._rpc_url or ""),
            self._sk)

    async def connect(self) -> None:
        if self._sdk is None:
            self._sdk = self._build_sdk()
        self._loop = asyncio.get_running_loop()
        # croo's connect_websocket() already dials the socket and starts the reader
        # loop, returning a live stream. Calling EventStream.connect() again opens a
        # SECOND socket under the same SDK key, which the server closes as a duplicate
        # ("websocket policy violation (duplicate key)"). So register our handler on
        # the already-connected stream and do NOT reconnect. Events arriving before
        # on_any is registered are dropped, but we register at startup before issuing
        # any request, so no order/negotiation event is in flight yet.
        self._stream = await self._sdk.connect_websocket()
        self._stream.on_any(self._on_sdk_event)

    async def close(self) -> None:
        if self._stream is not None:
            await self._stream.close()
        if self._sdk is not None:
            await self._sdk.close()
        self._closed.set()

    async def run_forever(self) -> None:
        # EventStream pushes via callbacks on its own reader; just stay alive.
        await self._closed.wait()

    def on(self, event: CapEvent, handler: Handler) -> None:
        self._handlers.setdefault(event, []).append(handler)

    # --- event bridge: sync SDK callback (maybe off-loop) -> async router --
    def _on_sdk_event(self, ev) -> None:
        loop = self._loop
        if loop is None:
            return
        loop.call_soon_threadsafe(self._schedule_event, ev)

    def _schedule_event(self, ev) -> None:
        # Merge the typed Event fields over its raw dict so the translators see
        # both the entity detail (raw) and the typed ids/status.
        payload = dict(_g(ev, "raw", default={}) or {})
        for f in ("order_id", "negotiation_id", "service_id", "status", "reason"):
            v = _g(ev, f)
            if v is not None:
                payload.setdefault(f, v)
        self._spawn(self._dispatch(_g(ev, "type", default=""), payload))

    # --- event router -----------------------------------------------------
    async def _dispatch(self, event, payload) -> None:
        ev = self._to_event(event)
        if ev is None:
            return
        # Resolve requester-side futures SYNCHRONOUSLY, before scheduling any
        # handler task, so a blocked handler can never starve a waiter.
        if ev is CapEvent.ORDER_CREATED:
            order = self._order_from(payload)
            key = order.negotiation_id or order.order_id
            self._resolve(self._created_waiters, self._created_ready, key, order)
        elif ev in (CapEvent.NEGOTIATION_REJECTED, CapEvent.NEGOTIATION_EXPIRED):
            neg = self._neg_from(payload)
            code = "rejected" if ev is CapEvent.NEGOTIATION_REJECTED else "expired"
            self._reject(self._created_waiters, self._created_errors,
                         neg.negotiation_id,
                         CapError(f"negotiation {code}", code=code))
        elif ev in _TERMINAL:
            order = self._order_from(payload)
            self._resolve(self._done_waiters, self._done_ready, order.order_id, order)
        # Fan out to provider handlers as background tasks (NOT awaited inline):
        # the orchestrator's ORDER_PAID handler itself awaits sub-order events on
        # this same router, so awaiting it here would deadlock a sequential WS pump.
        domain = (self._neg_from(payload) if "NEGOTIATION" in ev.value
                  else self._order_from(payload))
        for handler in list(self._handlers.get(ev, [])):
            self._spawn(handler(domain), handler_task=True)

    @staticmethod
    def _to_event(event) -> Optional[CapEvent]:
        if isinstance(event, CapEvent):
            return event
        s = str(event)
        if s in _WIRE_TO_EVENT:
            return _WIRE_TO_EVENT[s]
        return CapEvent.__members__.get(s)  # accept member NAME (tests)

    def _spawn(self, coro, *, handler_task: bool = False) -> None:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        if handler_task:
            task.add_done_callback(self._on_handler_done)
        else:
            task.add_done_callback(self._tasks.discard)

    def _on_handler_done(self, task: asyncio.Task) -> None:
        self._tasks.discard(task)
        if not task.cancelled() and task.exception() is not None:
            print(f"[real_cap] handler task failed: {task.exception()!r}")

    @staticmethod
    def _resolve(waiters, ready, key, value) -> None:
        fut = waiters.pop(key, None)
        if fut is not None and not fut.done():
            fut.set_result(value)
        else:
            ready[key] = value

    @staticmethod
    def _reject(waiters, errors, key, exc) -> None:
        fut = waiters.pop(key, None)
        if fut is not None and not fut.done():
            fut.set_exception(exc)
        else:
            errors[key] = exc

    async def _await(self, waiters, ready, key, timeout, errors=None) -> Order:
        if errors is not None and key in errors:
            raise errors.pop(key)
        if key in ready:
            return ready.pop(key)
        fut = asyncio.get_running_loop().create_future()
        waiters[key] = fut
        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError as exc:
            waiters.pop(key, None)
            raise CapError(f"timed out waiting for {key}", code="timeout") from exc

    # --- error boundary: normalize SDK exceptions to CapError -------------
    async def _guard(self, coro):
        import croo
        try:
            return await coro
        except CapError:
            raise
        except croo.InsufficientBalanceError as exc:
            raise CapError(str(exc) or "insufficient balance",
                           code="insufficient_balance") from exc
        except croo.APIError as exc:
            raise CapError(str(exc) or getattr(exc, "reason", "api error"),
                           code=self._api_code(exc)) from exc
        except Exception as exc:  # adapter boundary
            raise CapError(str(exc), code=getattr(exc, "code", None)) from exc

    @staticmethod
    def _api_code(exc) -> str:
        import croo
        if croo.is_not_found(exc):
            return "not_found"
        if croo.is_invalid_status(exc):
            return "invalid_status"
        if croo.is_unauthorized(exc):
            return "unauthorized"
        if croo.is_forbidden(exc):
            return "forbidden"
        if croo.is_invalid_params(exc):
            return "invalid_params"
        return getattr(exc, "reason", None) or "api_error"

    # --- requester --------------------------------------------------------
    async def negotiate_order(self, service_id, requirements) -> Negotiation:
        from croo import NegotiateOrderRequest
        req = NegotiateOrderRequest(service_id=service_id,
                                    requirements=json.dumps(requirements or {}))
        return self._neg_from(await self._guard(self._sdk.negotiate_order(req)))

    async def await_order_created(self, negotiation_id, timeout) -> Order:
        return await self._await(self._created_waiters, self._created_ready,
                                 negotiation_id, timeout, self._created_errors)

    async def pay_order(self, order_id) -> None:
        await self._guard(self._sdk.pay_order(order_id))

    async def await_completion(self, order_id, timeout) -> Order:
        return await self._await(self._done_waiters, self._done_ready,
                                 order_id, timeout)

    async def get_delivery(self, order_id) -> Delivery:
        return self._delivery_from(
            order_id, await self._guard(self._sdk.get_delivery(order_id)))

    async def get_download_url(self, file_id) -> str:
        return await self._guard(self._sdk.get_download_url(file_id))

    # --- provider ---------------------------------------------------------
    async def get_negotiation(self, negotiation_id) -> Negotiation:
        return self._neg_from(
            await self._guard(self._sdk.get_negotiation(negotiation_id)))

    async def accept_negotiation(self, negotiation_id, fund_address=None) -> Order:
        if fund_address:
            res = await self._guard(self._sdk.accept_negotiation_with_fund_address(
                negotiation_id, fund_address))
        else:
            res = await self._guard(self._sdk.accept_negotiation(negotiation_id))
        order = self._order_from(_g(res, "order", default=res))
        # Backfill requirements (the SDK Order carries none) from the negotiation
        # so the provider's ORDER_PAID handler can read order.requirements later.
        neg = _g(res, "negotiation")
        if neg is not None:
            reqs = _loads(_g(neg, "requirements", default={}))
            if order.order_id and reqs:
                self._req_by_order[order.order_id] = reqs
                if not order.requirements:
                    order.requirements = reqs
        return order

    async def reject_negotiation(self, negotiation_id, reason="") -> None:
        await self._guard(self._sdk.reject_negotiation(negotiation_id, reason))

    async def deliver_order(self, order_id, deliverable, file_url=None) -> None:
        # file_url (pre-uploaded object_key) is not yet threaded into the SDK
        # delivery call; deliverables are small JSON carried in deliverable_text.
        # Large-file delivery via object_key is a §C2 / Task 21 follow-up.
        from croo import DeliverOrderRequest
        req = DeliverOrderRequest(deliverable_type="text", deliverable_schema="",
                                  deliverable_text=json.dumps(deliverable or {}))
        await self._guard(self._sdk.deliver_order(order_id, req))

    async def reject_order(self, order_id, reason="") -> None:
        await self._guard(self._sdk.reject_order(order_id, reason))

    async def upload_file(self, content, filename) -> str:
        return await self._guard(self._sdk.upload_file(filename, content))

    # --- both -------------------------------------------------------------
    async def get_order(self, order_id) -> Order:
        return self._order_from(await self._guard(self._sdk.get_order(order_id)))

    async def list_orders(self) -> list:
        from croo import ListOptions
        out: dict[str, Order] = {}
        for role in ("buyer", "provider"):
            for o in await self._guard(self._sdk.list_orders(ListOptions(role=role))):
                order = self._order_from(o)
                out[order.order_id] = order
        return list(out.values())

    async def list_negotiations(self) -> list:
        from croo import ListOptions
        out: dict[str, Negotiation] = {}
        for role in ("buyer", "provider"):
            for n in await self._guard(
                    self._sdk.list_negotiations(ListOptions(role=role))):
                neg = self._neg_from(n)
                out[neg.negotiation_id] = neg
        return list(out.values())

    async def get_balance(self, address=None) -> float:
        # The croo SDK exposes no numeric balance getter (only
        # balance.check_erc20_balance, which raises/returns None and needs the AA
        # wallet address — unresolved, cap-sdk-interface.md §C2). Inject balance_fn
        # to supply it; until then the orchestrator working-capital precheck is
        # blocked on the live path.
        if self._balance_fn is not None:
            return float(await self._balance_fn(address))
        raise CapError(
            "get_balance unavailable: croo SDK exposes no numeric balance; wire "
            "balance_fn once the AA wallet address is resolved (cap-sdk-interface.md "
            "§C2)", code="unsupported")
