import pytest
from coo_agent.cap_client import CapError, CapEvent, OrderStatus, is_insufficient_balance
from coo_agent.testing.fake_cap import FakeExchange, FakeCapClient, Fault


def _wire_provider(client, service_id, deliverable):
    async def on_neg(neg):
        if neg.service_id == service_id:
            await client.accept_negotiation(neg.negotiation_id)
    async def on_paid(order):
        if order.service_id == service_id:
            await client.deliver_order(order.order_id, deliverable)
    client.on(CapEvent.NEGOTIATION_CREATED, on_neg)
    client.on(CapEvent.ORDER_PAID, on_paid)


async def test_happy_order_settles_balances():
    ex = FakeExchange(fee_rate=0.1)
    prov = FakeCapClient(ex, "prov", serves=[("svc", 0.10)])
    req = FakeCapClient(ex, "req")
    ex.credit("req", 1.0)
    _wire_provider(prov, "svc", {"ok": True})
    neg = await req.negotiate_order("svc", {"x": 1})
    order = await req.await_order_created(neg.negotiation_id, timeout=1)
    await req.pay_order(order.order_id)
    final = await req.await_completion(order.order_id, timeout=1)
    assert final.status is OrderStatus.completed
    assert (await req.get_delivery(order.order_id)).deliverable == {"ok": True}
    assert await req.get_balance() == pytest.approx(0.90)
    assert await prov.get_balance() == pytest.approx(0.09)


async def test_insufficient_balance():
    ex = FakeExchange()
    prov = FakeCapClient(ex, "prov", serves=[("svc", 0.10)])
    _wire_provider(prov, "svc", {})
    req = FakeCapClient(ex, "req")  # no funds
    neg = await req.negotiate_order("svc", {})
    order = await req.await_order_created(neg.negotiation_id, timeout=1)
    with pytest.raises(CapError) as ei:
        await req.pay_order(order.order_id)
    assert is_insufficient_balance(ei.value)


async def test_reject_negotiation_fault():
    ex = FakeExchange()
    FakeCapClient(ex, "prov", serves=[("svc", 0.10)], fault=Fault(reject_negotiation=True))
    req = FakeCapClient(ex, "req"); ex.credit("req", 1.0)
    neg = await req.negotiate_order("svc", {})
    with pytest.raises(CapError):
        await req.await_order_created(neg.negotiation_id, timeout=1)


async def test_silent_provider_times_out_and_refunds():
    ex = FakeExchange()
    prov = FakeCapClient(ex, "prov", serves=[("svc", 0.10)], fault=Fault(silent_on_pay=True))
    async def on_neg(neg):
        await prov.accept_negotiation(neg.negotiation_id)
    prov.on(CapEvent.NEGOTIATION_CREATED, on_neg)
    req = FakeCapClient(ex, "req"); ex.credit("req", 1.0)
    neg = await req.negotiate_order("svc", {})
    order = await req.await_order_created(neg.negotiation_id, timeout=1)
    await req.pay_order(order.order_id)
    with pytest.raises(CapError):
        await req.await_completion(order.order_id, timeout=0.05)
    assert await req.get_balance() == pytest.approx(1.0)  # refunded


async def test_reject_order_refunds_requester():
    ex = FakeExchange()
    prov = FakeCapClient(ex, "prov", serves=[("svc", 0.10)])
    async def on_neg(neg): await prov.accept_negotiation(neg.negotiation_id)
    async def on_paid(order): await prov.reject_order(order.order_id, "nope")
    prov.on(CapEvent.NEGOTIATION_CREATED, on_neg)
    prov.on(CapEvent.ORDER_PAID, on_paid)
    req = FakeCapClient(ex, "req"); ex.credit("req", 1.0)
    neg = await req.negotiate_order("svc", {})
    order = await req.await_order_created(neg.negotiation_id, timeout=1)
    await req.pay_order(order.order_id)
    final = await req.await_completion(order.order_id, timeout=1)
    assert final.status is OrderStatus.rejected
    assert await req.get_balance() == pytest.approx(1.0)
