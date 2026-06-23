import pytest
from pydantic import BaseModel

from coo_agent.cap_client import OrderStatus, CapError
from coo_agent.provider_runtime import ProviderRuntime
from coo_agent.testing.fake_cap import FakeExchange, FakeCapClient, Fault


class Req(BaseModel):
    text: str


class Deliv(BaseModel):
    echoed: str


SERVICE = "svc_echo"


def parse(requirements: dict) -> Req:
    return Req.model_validate(requirements)


def make_work(calls):
    async def work(req: Req) -> Deliv:
        calls.append(req.text)
        return Deliv(echoed=req.text.upper())
    return work


@pytest.fixture
def wired():
    ex = FakeExchange(fee_rate=0.1)
    provider = FakeCapClient(ex, "provider", serves=[(SERVICE, 0.05)])
    requester = FakeCapClient(ex, "requester")
    ex.credit("requester", 1.0)
    return ex, provider, requester


async def test_happy_path_delivers_and_settles(wired):
    ex, provider, requester = wired
    calls = []
    ProviderRuntime(provider, SERVICE, parse, make_work(calls)).install()

    neg = await requester.negotiate_order(SERVICE, {"text": "hello"})
    order = await requester.await_order_created(neg.negotiation_id, timeout=1)
    await requester.pay_order(order.order_id)
    completed = await requester.await_completion(order.order_id, timeout=1)
    delivery = await requester.get_delivery(order.order_id)

    assert calls == ["hello"]
    assert completed.status is OrderStatus.completed
    assert delivery.deliverable == {"echoed": "HELLO"}
    assert ex.balances["requester"] == pytest.approx(0.95)
    assert ex.balances["provider"] == pytest.approx(0.045)


async def test_invalid_requirements_rejects_negotiation(wired):
    ex, provider, requester = wired
    ProviderRuntime(provider, SERVICE, parse, make_work([])).install()

    neg = await requester.negotiate_order(SERVICE, {"wrong": "field"})
    with pytest.raises(CapError) as ei:
        await requester.await_order_created(neg.negotiation_id, timeout=1)
    assert ei.value.code == "rejected"
    assert ex.balances["requester"] == pytest.approx(1.0)


async def test_work_failure_rejects_order_and_refunds(wired):
    ex, provider, requester = wired

    async def boom(req: Req) -> Deliv:
        raise RuntimeError("model exploded")

    ProviderRuntime(provider, SERVICE, parse, boom).install()

    neg = await requester.negotiate_order(SERVICE, {"text": "hi"})
    order = await requester.await_order_created(neg.negotiation_id, timeout=1)
    await requester.pay_order(order.order_id)
    completed = await requester.await_completion(order.order_id, timeout=1)

    assert completed.status is OrderStatus.rejected
    assert ex.balances["requester"] == pytest.approx(1.0)
    assert ex.balances.get("provider", 0.0) == pytest.approx(0.0)


async def test_large_deliverable_is_uploaded(wired):
    ex, provider, requester = wired

    async def big(req: Req) -> Deliv:
        return Deliv(echoed="x" * 1000)

    ProviderRuntime(provider, SERVICE, parse, big, upload_threshold=100).install()

    neg = await requester.negotiate_order(SERVICE, {"text": "hi"})
    order = await requester.await_order_created(neg.negotiation_id, timeout=1)
    await requester.pay_order(order.order_id)
    await requester.await_completion(order.order_id, timeout=1)
    delivery = await requester.get_delivery(order.order_id)

    assert delivery.file_url is not None
    assert delivery.file_url.startswith("fake://upload/")


async def test_precheck_rejects_negotiation(wired):
    ex, provider, requester = wired

    async def precheck(req: Req) -> None:
        raise RuntimeError("cannot afford")

    ProviderRuntime(provider, SERVICE, parse, make_work([]),
                    precheck_fn=precheck).install()

    neg = await requester.negotiate_order(SERVICE, {"text": "hi"})
    with pytest.raises(CapError) as ei:
        await requester.await_order_created(neg.negotiation_id, timeout=1)
    assert ei.value.code == "rejected"
