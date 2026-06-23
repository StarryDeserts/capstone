import pytest
from pydantic import BaseModel

from coo_agent.requester import hire, HireResult
from coo_agent.provider_runtime import ProviderRuntime
from coo_agent.testing.fake_cap import FakeExchange, FakeCapClient, Fault


class Req(BaseModel):
    text: str


class Deliv(BaseModel):
    echoed: str


SERVICE = "svc_echo"


def parse(requirements: dict) -> Req:
    return Req.model_validate(requirements)


async def echo_work(req: Req) -> Deliv:
    return Deliv(echoed=req.text.upper())


def _wire(fault=None, work_fn=echo_work):
    ex = FakeExchange(fee_rate=0.1)
    provider = FakeCapClient(ex, "provider", serves=[(SERVICE, 0.05)], fault=fault)
    requester = FakeCapClient(ex, "requester")
    ex.credit("requester", 1.0)
    ProviderRuntime(provider, SERVICE, parse, work_fn).install()
    return ex, requester


async def test_hire_success_returns_deliverable():
    ex, requester = _wire()
    result = await hire(requester, SERVICE, {"text": "hi"}, timeout=1)
    assert result.ok is True
    assert result.deliverable == {"echoed": "HI"}
    assert result.status == "completed"
    assert result.price_usdc == pytest.approx(0.05)
    assert result.order_id is not None
    assert result.error is None


async def test_hire_negotiation_rejected_returns_failure():
    ex, requester = _wire(fault=Fault(reject_negotiation=True))
    result = await hire(requester, SERVICE, {"text": "hi"}, timeout=1)
    assert result.ok is False
    assert result.status == "rejected"
    assert result.deliverable is None
    assert ex.balances["requester"] == pytest.approx(1.0)


async def test_hire_unknown_service_returns_failure():
    ex, requester = _wire()
    result = await hire(requester, "svc_missing", {"text": "hi"}, timeout=1)
    assert result.ok is False
    assert result.status == "not_found"
    assert result.order_id is None


async def test_hire_provider_timeout_refunds_and_fails():
    ex, requester = _wire(fault=Fault(silent_on_pay=True))
    result = await hire(requester, SERVICE, {"text": "hi"}, timeout=0.05)
    assert result.ok is False
    assert result.status == "timeout"
    assert ex.balances["requester"] == pytest.approx(1.0)


async def test_hire_work_failure_returns_rejected_and_refunds():
    async def boom(req: Req) -> Deliv:
        raise RuntimeError("nope")

    ex, requester = _wire(work_fn=boom)
    result = await hire(requester, SERVICE, {"text": "hi"}, timeout=1)
    assert result.ok is False
    assert result.status == "rejected"
    assert ex.balances["requester"] == pytest.approx(1.0)
