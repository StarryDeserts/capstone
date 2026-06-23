import pytest

from coo_agent.catalog import Catalog
from coo_agent.config import Config
from coo_agent.orchestrator import (
    OrchestratorError, make_orchestrator_precheck, make_orchestrator_work_fn,
)
from coo_agent.planner import Plan, PlanStep
from coo_agent.provider_runtime import ProviderRuntime
from coo_agent.requester import hire
from coo_agent.schemas import (
    Depth, FactCheckDeliverable, FactCheckRequest, Finding, FormatDeliverable,
    FormatRequest, OrchestratorRequest, ResearchDeliverable, ResearchRequest,
    Style, Verdict, VerdictItem,
)
from coo_agent.testing.fake_cap import FakeExchange, FakeCapClient, Fault


def _p_research(d): return ResearchRequest.model_validate(d)
def _p_verify(d): return FactCheckRequest.model_validate(d)
def _p_format(d): return FormatRequest.model_validate(d)


async def _research_work(req: ResearchRequest) -> ResearchDeliverable:
    return ResearchDeliverable(findings=[
        Finding(statement=f"F{i}:{req.query}", source_url=f"https://e/{i}",
                source_title=f"T{i}", snippet="s", confidence=0.9)
        for i in range(req.num_sources)])


async def _verify_work(req: FactCheckRequest) -> FactCheckDeliverable:
    return FactCheckDeliverable(verdicts=[
        VerdictItem(statement=c.statement, verdict=Verdict.supported, confidence=0.8)
        for c in req.claims])


async def _format_work(req: FormatRequest) -> FormatDeliverable:
    return FormatDeliverable(report_markdown=f"# {req.title}\n\nok", references=[])


def _cfg():
    return Config(api_url="", ws_url="", rpc_url=None, anthropic_api_key="",
                  model="m", fee_rate=0.0, margin_floor=0.0,
                  orchestrator_price=0.50, agents={})


class StubPlanner:
    def __init__(self, steps, title="T", fanout=1):
        self._plan = Plan(steps=steps, fanout=fanout, est_cost=0.0, title=title)

    async def plan(self, req, catalog, budget):
        return self._plan


def _fmt_step(title="T", style="report"):
    return PlanStep(role="format",
                    inputs={"title": title, "style": style, "audience": None},
                    critical=True, group=2)


CATALOG_2R = (
    "research:\n"
    "  - { service_id: svc_r1, price_usdc: 0.05, tags: [] }\n"
    "  - { service_id: svc_r2, price_usdc: 0.05, tags: [] }\n"
    "verify:\n  - { service_id: svc_v, price_usdc: 0.05, tags: [] }\n"
    "format:\n  - { service_id: svc_f, price_usdc: 0.05, tags: [] }\n"
)


def _catalog(tmp_path, body):
    p = tmp_path / "catalog.yaml"
    p.write_text(body)
    return Catalog.load(str(p))


async def test_research_fails_over_to_alternate(tmp_path):
    catalog = _catalog(tmp_path, CATALOG_2R)
    ex = FakeExchange(fee_rate=0.0)
    FakeCapClient(ex, "r1", serves=[("svc_r1", 0.05)],
                  fault=Fault(reject_negotiation=True))   # svc_r1 always rejects
    good = FakeCapClient(ex, "r2", serves=[("svc_r2", 0.05)])
    fmtp = FakeCapClient(ex, "f", serves=[("svc_f", 0.05)])
    orch = FakeCapClient(ex, "orchestrator")
    ex.credit("orchestrator", 1.0)
    ProviderRuntime(good, "svc_r2", _p_research, _research_work).install()
    ProviderRuntime(fmtp, "svc_f", _p_format, _format_work).install()

    planner = StubPlanner([
        PlanStep("research", {"query": "X", "num_sources": 2}, True, 0), _fmt_step()])
    work = make_orchestrator_work_fn(orch, catalog, planner, _cfg(), step_timeout=1)
    result = await work(OrchestratorRequest(topic="X", depth=Depth.quick, format=Style.report))

    research = [s for s in result.meta.sub_orders if s.role == "research"]
    assert len(research) == 2
    assert research[0].service_id == "svc_r1" and research[0].status == "rejected"
    assert research[1].service_id == "svc_r2" and research[1].status == "completed"
    assert len(result.citations) == 2


async def test_all_research_failure_raises(tmp_path):
    catalog = _catalog(tmp_path, CATALOG_2R)
    ex = FakeExchange(fee_rate=0.0)
    FakeCapClient(ex, "r1", serves=[("svc_r1", 0.05)], fault=Fault(reject_negotiation=True))
    FakeCapClient(ex, "r2", serves=[("svc_r2", 0.05)], fault=Fault(reject_negotiation=True))
    FakeCapClient(ex, "f", serves=[("svc_f", 0.05)])
    orch = FakeCapClient(ex, "orchestrator")
    ex.credit("orchestrator", 1.0)

    planner = StubPlanner([
        PlanStep("research", {"query": "X", "num_sources": 1}, True, 0), _fmt_step()])
    work = make_orchestrator_work_fn(orch, catalog, planner, _cfg(), step_timeout=1)
    with pytest.raises(OrchestratorError):
        await work(OrchestratorRequest(topic="X", depth=Depth.quick, format=Style.report))


async def test_research_failure_refunds_customer(tmp_path):
    catalog = _catalog(tmp_path, CATALOG_2R)
    ex = FakeExchange(fee_rate=0.0)
    FakeCapClient(ex, "r1", serves=[("svc_r1", 0.05)], fault=Fault(reject_negotiation=True))
    FakeCapClient(ex, "r2", serves=[("svc_r2", 0.05)], fault=Fault(reject_negotiation=True))
    FakeCapClient(ex, "f", serves=[("svc_f", 0.05)])
    orch = FakeCapClient(ex, "orchestrator", serves=[("svc_o", 0.50)])
    customer = FakeCapClient(ex, "customer")
    ex.credit("orchestrator", 1.0)
    ex.credit("customer", 1.0)

    planner = StubPlanner([
        PlanStep("research", {"query": "X", "num_sources": 1}, True, 0), _fmt_step()])
    work = make_orchestrator_work_fn(orch, catalog, planner, _cfg(), step_timeout=1)
    ProviderRuntime(orch, "svc_o",
                    lambda d: OrchestratorRequest.model_validate(d), work).install()

    result = await hire(customer, "svc_o",
                        {"topic": "X", "depth": "standard", "format": "report"},
                        timeout=2)
    assert result.ok is False
    assert result.status == "rejected"
    assert ex.balances["customer"] == pytest.approx(1.0)        # refunded
    assert ex.balances["orchestrator"] == pytest.approx(1.0)    # never paid out


async def test_verify_failure_degrades_to_unverified(tmp_path):
    catalog = _catalog(tmp_path, CATALOG_2R)
    ex = FakeExchange(fee_rate=0.0)
    r = FakeCapClient(ex, "r", serves=[("svc_r1", 0.05)])
    FakeCapClient(ex, "v", serves=[("svc_v", 0.05)], fault=Fault(reject_negotiation=True))
    fmtp = FakeCapClient(ex, "f", serves=[("svc_f", 0.05)])
    orch = FakeCapClient(ex, "orchestrator")
    ex.credit("orchestrator", 1.0)
    ProviderRuntime(r, "svc_r1", _p_research, _research_work).install()
    ProviderRuntime(fmtp, "svc_f", _p_format, _format_work).install()

    planner = StubPlanner([
        PlanStep("research", {"query": "X", "num_sources": 2}, True, 0),
        PlanStep("verify", {"strictness": "normal"}, False, 1),
        _fmt_step()])
    work = make_orchestrator_work_fn(orch, catalog, planner, _cfg(), step_timeout=1)
    result = await work(OrchestratorRequest(topic="X", depth=Depth.standard, format=Style.report))

    verify_orders = [s for s in result.meta.sub_orders if s.role == "verify"]
    assert verify_orders and all(s.status == "rejected" for s in verify_orders)
    assert all(c.verdict == "unverified" for c in result.citations)
    assert result.report_markdown.startswith("# ")


async def test_format_failure_degrades_to_fallback(tmp_path):
    catalog = _catalog(tmp_path, CATALOG_2R)
    ex = FakeExchange(fee_rate=0.0)
    r = FakeCapClient(ex, "r", serves=[("svc_r1", 0.05)])
    FakeCapClient(ex, "f", serves=[("svc_f", 0.05)], fault=Fault(reject_negotiation=True))
    orch = FakeCapClient(ex, "orchestrator")
    ex.credit("orchestrator", 1.0)
    ProviderRuntime(r, "svc_r1", _p_research, _research_work).install()

    planner = StubPlanner([
        PlanStep("research", {"query": "Topic", "num_sources": 2}, True, 0),
        _fmt_step(title="My Title")])
    work = make_orchestrator_work_fn(orch, catalog, planner, _cfg(), step_timeout=1)
    result = await work(OrchestratorRequest(topic="Topic", depth=Depth.quick, format=Style.report))

    fmt_orders = [s for s in result.meta.sub_orders if s.role == "format"]
    assert fmt_orders and all(s.status == "rejected" for s in fmt_orders)
    assert result.report_markdown.startswith("# My Title")   # fallback report
    assert "F0:Topic" in result.report_markdown
    assert len(result.citations) == 2


async def test_precheck_rejects_when_underfunded(tmp_path):
    catalog = _catalog(tmp_path, CATALOG_2R)
    ex = FakeExchange(fee_rate=0.0)
    orch = FakeCapClient(ex, "orchestrator")
    ex.credit("orchestrator", 1.0)
    precheck = make_orchestrator_precheck(orch, _cfg())   # budget == 0.50

    await precheck(None)               # 1.0 >= 0.50, no raise
    ex.balances["orchestrator"] = 0.10
    with pytest.raises(OrchestratorError):
        await precheck(None)
