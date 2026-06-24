import asyncio
import json
from types import SimpleNamespace

import croo
import pytest

from coo_agent.cap_client import (CapError, CapEvent, OrderStatus,
                                   is_insufficient_balance, is_invalid_status,
                                   is_not_found)
from coo_agent.real_cap import RealCapClient


class _SDKErr(Exception):
    def __init__(self, msg, code):
        super().__init__(msg)
        self.code = code


class _FakeStream:
    def __init__(self):
        self.cb = None

    def on_any(self, handler):
        self.cb = handler

    async def connect(self):
        return None

    async def close(self):
        return None


class FakeSDK:
    """Stand-in for croo.AgentClient: models the REAL shapes (request DTOs in,
    result objects out), records calls, lets tests inject errors."""

    def __init__(self):
        self.calls = []
        self.raise_on = {}  # method name -> exception to raise
        self.stream = _FakeStream()

    def _maybe_raise(self, name):
        if name in self.raise_on:
            raise self.raise_on[name]

    async def connect_websocket(self):
        return self.stream

    async def close(self):
        self.calls.append(("close",))

    async def negotiate_order(self, req):
        self._maybe_raise("negotiate_order")
        return SimpleNamespace(negotiation_id="neg1", service_id=req.service_id,
                               requester_agent_id="did", requirements=req.requirements)

    def _accept_result(self, negotiation_id):
        order = SimpleNamespace(order_id="o1", service_id="svc", status="created",
                                price="0.05", negotiation_id=negotiation_id)
        neg = SimpleNamespace(negotiation_id=negotiation_id,
                              requirements=json.dumps({"topic": "t"}))
        return SimpleNamespace(order=order, negotiation=neg)

    async def accept_negotiation(self, negotiation_id):
        self._maybe_raise("accept_negotiation")
        self.calls.append(("accept", negotiation_id, None))
        return self._accept_result(negotiation_id)

    async def accept_negotiation_with_fund_address(self, negotiation_id,
                                                   provider_fund_address):
        self._maybe_raise("accept_negotiation")
        self.calls.append(("accept", negotiation_id, provider_fund_address))
        return self._accept_result(negotiation_id)

    async def pay_order(self, order_id):
        self._maybe_raise("pay_order")
        self.calls.append(("pay", order_id))
        return SimpleNamespace(order=None, tx_hash="0xpay")

    async def deliver_order(self, order_id, req):
        self._maybe_raise("deliver_order")
        self.calls.append(("deliver", order_id, req.deliverable_type,
                           req.deliverable_text))
        return SimpleNamespace(order=None, delivery=None, tx_hash="0xdeliver")

    async def reject_order(self, order_id, reason):
        self.calls.append(("rej_order", order_id, reason))

    async def reject_negotiation(self, negotiation_id, reason):
        self.calls.append(("rej_neg", negotiation_id, reason))

    async def upload_file(self, file_name, body):
        self.calls.append(("upload", file_name, body))
        return "objkey/" + file_name

    async def get_delivery(self, order_id):
        return SimpleNamespace(order_id=order_id,
                               deliverable_text=json.dumps({"a": 1}),
                               content_hash="0x", status="submitted")

    async def get_download_url(self, object_key):
        return "https://dl/" + object_key

    async def get_order(self, order_id):
        self._maybe_raise("get_order")
        return SimpleNamespace(order_id=order_id, service_id="svc",
                               status="completed", price="0.05")

    async def list_orders(self, opts=None):
        return [SimpleNamespace(order_id="o1", service_id="svc",
                                status="completed", price="0.05")]

    async def list_negotiations(self, opts=None):
        return [SimpleNamespace(negotiation_id="neg1", service_id="svc",
                                requester_agent_id="did", requirements="{}")]


async def _connected(fake=None, **kw):
    fake = fake or FakeSDK()
    cap = RealCapClient("croo_sk_x", "api", "ws", sdk=fake, **kw)
    await cap.connect()
    return cap, fake


async def test_negotiate_and_accept_translate():
    cap, fake = await _connected()
    neg = await cap.negotiate_order("svc", {"topic": "t"})
    assert neg.negotiation_id == "neg1" and neg.service_id == "svc"
    assert neg.requirements == {"topic": "t"}            # JSON string decoded
    order = await cap.accept_negotiation("neg1", fund_address="0xAA")
    assert order.order_id == "o1" and order.status is OrderStatus.created
    assert order.price_usdc == 0.05                      # price str -> float
    assert ("accept", "neg1", "0xAA") in fake.calls      # used with-fund variant


async def test_await_order_created_from_buffered_event():
    cap, _ = await _connected()
    await cap._dispatch("order_created", {
        "order_id": "o1", "service_id": "svc", "status": "created",
        "price": "0.05", "negotiation_id": "neg1"})
    order = await cap.await_order_created("neg1", timeout=1)
    assert order.order_id == "o1"


async def test_await_completion_resolves_on_later_event():
    cap, _ = await _connected()
    task = asyncio.create_task(cap.await_completion("o1", timeout=1))
    await asyncio.sleep(0)  # let the awaiter register its future first
    await cap._dispatch("order_completed", {
        "order_id": "o1", "service_id": "svc", "status": "completed", "price": "0.05"})
    order = await task
    assert order.status is OrderStatus.completed


async def test_await_order_created_times_out():
    cap, _ = await _connected()
    with pytest.raises(CapError) as ei:
        await cap.await_order_created("missing", timeout=0.05)
    assert ei.value.code == "timeout"


async def test_await_order_created_fails_fast_on_rejection():
    cap, _ = await _connected()
    task = asyncio.create_task(cap.await_order_created("neg1", timeout=5))
    await asyncio.sleep(0)
    await cap._dispatch("order_negotiation_rejected", {
        "negotiation_id": "neg1", "service_id": "svc", "requirements": "{}"})
    with pytest.raises(CapError) as ei:
        await task
    assert ei.value.code == "rejected"


async def test_event_name_alias_accepted():
    cap, _ = await _connected()
    await cap._dispatch("ORDER_CREATED", {  # member NAME, not wire string
        "order_id": "o9", "negotiation_id": "negX", "status": "created", "price": "0.1"})
    order = await cap.await_order_created("negX", timeout=1)
    assert order.order_id == "o9"


async def test_provider_handler_invoked_on_negotiation_event():
    cap, _ = await _connected()
    seen = []

    async def handler(neg):
        seen.append(neg)

    cap.on(CapEvent.NEGOTIATION_CREATED, handler)
    await cap._dispatch("order_negotiation_created", {
        "negotiation_id": "n1", "service_id": "svc",
        "requester_agent_id": "did", "requirements": json.dumps({"q": 1})})
    await asyncio.sleep(0)  # handlers run as background tasks; let it execute
    assert seen and seen[0].negotiation_id == "n1" and seen[0].requirements == {"q": 1}


async def test_requirements_backfilled_for_paid_order():
    # SDK Order carries no requirements; accept caches the negotiation's, so a
    # later ORDER_PAID (which lacks them) still yields order.requirements.
    cap, _ = await _connected()
    await cap.accept_negotiation("neg1")           # caches {"topic":"t"} for o1
    seen = []

    async def handler(order):
        seen.append(order)

    cap.on(CapEvent.ORDER_PAID, handler)
    await cap._dispatch("order_paid", {
        "order_id": "o1", "service_id": "svc", "status": "paid", "price": "0.05"})
    await asyncio.sleep(0)
    assert seen and seen[0].requirements == {"topic": "t"}


async def test_on_sdk_event_bridge_schedules_dispatch():
    # The sync on_any callback (possibly off-loop) must reach the async router.
    cap, _ = await _connected()
    task = asyncio.create_task(cap.await_completion("o1", timeout=1))
    await asyncio.sleep(0)
    ev = SimpleNamespace(
        type="order_completed",
        raw={"order_id": "o1", "status": "completed", "price": "0.05"},
        order_id="o1", negotiation_id=None, service_id="svc",
        status="completed", reason=None)
    cap._on_sdk_event(ev)          # sync entry point
    order = await task
    assert order.status is OrderStatus.completed


async def test_sdk_error_normalized_to_cap_error():
    fake = FakeSDK()
    fake.raise_on["accept_negotiation"] = _SDKErr("bad status", "invalid_status")
    cap, _ = await _connected(fake)
    with pytest.raises(CapError) as ei:
        await cap.accept_negotiation("n1")
    assert is_invalid_status(ei.value)


async def test_apierror_mapped_via_reason_predicate():
    fake = FakeSDK()
    fake.raise_on["get_order"] = croo.APIError(404, 1001, "SERVICE_NOT_FOUND", "nope")
    cap, _ = await _connected(fake)
    with pytest.raises(CapError) as ei:
        await cap.get_order("o1")
    assert is_not_found(ei.value)     # APIError.reason endswith _NOT_FOUND -> not_found


async def test_insufficient_balance_error_mapped():
    fake = FakeSDK()
    fake.raise_on["pay_order"] = croo.InsufficientBalanceError("USDC", 100, 10)
    cap, _ = await _connected(fake)
    with pytest.raises(CapError) as ei:
        await cap.pay_order("o1")
    assert is_insufficient_balance(ei.value)


async def test_cap_error_passes_through_unchanged():
    fake = FakeSDK()
    fake.raise_on["pay_order"] = CapError("no funds", code="insufficient_balance")
    cap, _ = await _connected(fake)
    with pytest.raises(CapError) as ei:
        await cap.pay_order("o1")
    assert is_insufficient_balance(ei.value)


async def test_deliver_encodes_json_and_upload_passthrough():
    cap, fake = await _connected()
    await cap.deliver_order("o1", {"report_markdown": "# r"}, file_url="u")
    deliver = [c for c in fake.calls if c[0] == "deliver"][0]
    assert deliver[1] == "o1" and deliver[2] == "text"          # deliverable_type
    assert json.loads(deliver[3]) == {"report_markdown": "# r"}  # deliverable_text
    assert await cap.upload_file(b"x", "f.json") == "objkey/f.json"  # (file_name, body)
    delivery = await cap.get_delivery("o1")
    assert delivery.deliverable == {"a": 1}                      # deliverable_text decoded


async def test_get_balance_injected_and_unsupported_default():
    async def bal(addr):
        return 2.5

    cap, _ = await _connected(balance_fn=bal)
    assert await cap.get_balance() == 2.5

    cap2, _ = await _connected()
    with pytest.raises(CapError) as ei:
        await cap2.get_balance()
    assert ei.value.code == "unsupported"
