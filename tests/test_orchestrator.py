# tests/test_orchestrator.py
import pytest

from coo_agent.catalog import Catalog
from coo_agent.config import Config
from coo_agent.orchestrator import make_orchestrator_work_fn
from coo_agent.planner import Plan, PlanStep
from coo_agent.provider_runtime import ProviderRuntime
from coo_agent.schemas import (
    Depth, FactCheckDeliverable, FactCheckRequest, Finding, FormatDeliverable,
    FormatRequest, OrchestratorRequest, Reference, ResearchDeliverable,
    ResearchRequest, Style, Verdict, VerdictItem,
)
from coo_agent.testing.fake_cap import FakeExchange, FakeCapClient


def _parse_research(d): return ResearchRequest.model_validate(d)
def _parse_verify(d): return FactCheckRequest.model_validate(d)
def _parse_format(d): return FormatRequest.model_validate(d)


async def _research_work(req: ResearchRequest) -> ResearchDeliverable:
    return ResearchDeliverable(findings=[
        Finding(statement=f"Fact {i} about {req.query}",
                source_url=f"https://ex.com/{req.query}/{i}",
                source_title=f"T{i}", snippet="snip", confidence=0.9)
        for i in range(req.num_sources)
    ])


async def _verify_work(req: FactCheckRequest) -> FactCheckDeliverable:
    return FactCheckDeliverable(verdicts=[
        VerdictItem(statement=c.statement, verdict=Verdict.supported,
                    evidence_url=c.source_url or "", confidence=0.8)
        for c in req.claims
    ])


async def _format_work(req: FormatRequest) -> FormatDeliverable:
    body = "\n".join(f"- {f.statement}" for f in req.verified_findings)
    return FormatDeliverable(
        report_markdown=f"# {req.title}\n\n{body}",
        references=[Reference(n=i + 1, url=f.source_url, title=f.source_title)
                    for i, f in enumerate(req.verified_findings)])


def _cfg():
    return Config(api_url="", ws_url="", rpc_url=None, anthropic_api_key="",
                  model="claude-opus-4-7", fee_rate=0.0, margin_floor=0.0,
                  orchestrator_price=0.50, agents={})


class StubPlanner:
    def __init__(self, steps, title="Title", fanout=1):
        self._plan = Plan(steps=steps, fanout=fanout, est_cost=0.15, title=title)

    async def plan(self, req, catalog, budget):
        return self._plan


def _build(tmp_path):
    cat_yaml = tmp_path / "catalog.yaml"
    cat_yaml.write_text(
        "research:\n  - { service_id: svc_r, price_usdc: 0.05, tags: [] }\n"
        "verify:\n  - { service_id: svc_v, price_usdc: 0.05, tags: [] }\n"
        "format:\n  - { service_id: svc_f, price_usdc: 0.05, tags: [] }\n"
    )
    catalog = Catalog.load(str(cat_yaml))
    ex = FakeExchange(fee_rate=0.0)
    r = FakeCapClient(ex, "research", serves=[("svc_r", 0.05)])
    v = FakeCapClient(ex, "verify", serves=[("svc_v", 0.05)])
    f = FakeCapClient(ex, "format", serves=[("svc_f", 0.05)])
    orch = FakeCapClient(ex, "orchestrator")
    ex.credit("orchestrator", 1.0)
    ProviderRuntime(r, "svc_r", _parse_research, _research_work).install()
    ProviderRuntime(v, "svc_v", _parse_verify, _verify_work).install()
    ProviderRuntime(f, "svc_f", _parse_format, _format_work).install()
    return ex, orch, catalog


def _fmt_step(title, style, group=2):
    return PlanStep(role="format",
                    inputs={"title": title, "style": style, "audience": None},
                    critical=True, group=group)


async def test_happy_path_assembles_report_with_citations(tmp_path):
    ex, orch, catalog = _build(tmp_path)
    steps = [
        PlanStep(role="research", inputs={"query": "X", "num_sources": 2},
                 critical=True, group=0),
        PlanStep(role="verify", inputs={"strictness": "normal"},
                 critical=False, group=1),
        _fmt_step("State of X", "report"),
    ]
    work = make_orchestrator_work_fn(
        orch, catalog, StubPlanner(steps, title="State of X"), _cfg(), step_timeout=1)
    result = await work(OrchestratorRequest(
        topic="State of X", depth=Depth.standard, format=Style.report))

    assert result.report_markdown.startswith("# State of X")
    assert [s.role for s in result.meta.sub_orders] == ["research", "verify", "format"]
    assert all(s.status == "completed" for s in result.meta.sub_orders)
    assert result.meta.total_cost_usdc == pytest.approx(0.15)
    assert result.meta.model == "claude-opus-4-7"
    assert len(result.citations) == 2
    assert all(c.verdict == "supported" for c in result.citations)
    assert ex.balances["orchestrator"] == pytest.approx(0.85)  # paid 3 x 0.05


async def test_parallel_research_aggregates_findings(tmp_path):
    ex, orch, catalog = _build(tmp_path)
    steps = [
        PlanStep(role="research", inputs={"query": "A", "num_sources": 2},
                 critical=True, group=0),
        PlanStep(role="research", inputs={"query": "B", "num_sources": 3},
                 critical=True, group=0),
        _fmt_step("T", "report"),
    ]
    work = make_orchestrator_work_fn(
        orch, catalog, StubPlanner(steps, fanout=2), _cfg(), step_timeout=1)
    result = await work(OrchestratorRequest(
        topic="T", depth=Depth.deep, format=Style.report))

    research_orders = [s for s in result.meta.sub_orders if s.role == "research"]
    assert len(research_orders) == 2
    assert len(result.citations) == 5            # 2 + 3 findings
    assert all(c.verdict == "unverified" for c in result.citations)  # no verify step


async def test_no_verify_step_marks_citations_unverified(tmp_path):
    ex, orch, catalog = _build(tmp_path)
    steps = [
        PlanStep(role="research", inputs={"query": "X", "num_sources": 1},
                 critical=True, group=0),
        _fmt_step("X", "brief"),
    ]
    work = make_orchestrator_work_fn(orch, catalog, StubPlanner(steps), _cfg(), step_timeout=1)
    result = await work(OrchestratorRequest(
        topic="X", depth=Depth.quick, format=Style.brief))

    assert len(result.citations) == 1
    assert result.citations[0].verdict == "unverified"
    assert {s.role for s in result.meta.sub_orders} == {"research", "format"}
