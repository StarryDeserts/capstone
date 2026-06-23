import pytest
from pydantic import ValidationError
from coo_agent.schemas import (
    Depth, Style, Strictness, Verdict,
    OrchestratorRequest, Finding, Citation, SubOrder, OrchestratorMeta,
    OrchestratorDeliverable, ResearchRequest, ResearchDeliverable,
    Claim, FactCheckRequest, VerdictItem, FactCheckDeliverable,
    Reference, FormatRequest, FormatDeliverable,
)


def test_orchestrator_request_parses_and_defaults():
    r = OrchestratorRequest.model_validate({"topic": "x", "depth": "deep", "format": "report"})
    assert r.depth is Depth.deep and r.format is Style.report
    assert r.max_sources is None and r.audience is None


def test_orchestrator_request_rejects_bad_enum():
    with pytest.raises(ValidationError):
        OrchestratorRequest.model_validate({"topic": "x", "depth": "huge", "format": "report"})


def test_confidence_bounds_enforced():
    Finding(statement="s", source_url="u", source_title="t", snippet="p", confidence=1.0)
    with pytest.raises(ValidationError):
        Finding(statement="s", source_url="u", source_title="t", snippet="p", confidence=1.5)


def test_citation_allows_unverified_verdict():
    c = Citation(claim="c", source_url="u", snippet="s", confidence=0.5, verdict="unverified")
    assert c.verdict == "unverified"


def test_research_deliverable_roundtrips_json():
    d = ResearchDeliverable(findings=[Finding(statement="s", source_url="u",
        source_title="t", snippet="p", confidence=0.9, published_at="2026-01-01")])
    dumped = d.model_dump(mode="json")
    assert ResearchDeliverable.model_validate(dumped) == d


def test_factcheck_request_and_deliverable():
    req = FactCheckRequest(claims=[Claim(statement="s")], strictness="high")
    assert req.claims[0].source_url is None and req.strictness is Strictness.high
    dv = FactCheckDeliverable(verdicts=[VerdictItem(statement="s", verdict="supported",
        evidence_url="u", evidence_snippet="e", confidence=0.8)])
    assert dv.verdicts[0].verdict is Verdict.supported


def test_orchestrator_deliverable_full_shape():
    d = OrchestratorDeliverable(
        report_markdown="# r", citations=[],
        meta=OrchestratorMeta(sub_orders=[SubOrder(role="research", service_id="svc",
            order_id="o1", price_usdc=0.05, status="completed")],
            total_cost_usdc=0.05, model="claude-opus-4-7"))
    assert d.meta.sub_orders[0].role == "research"


def test_format_request_accepts_findings():
    f = FormatRequest(title="T", verified_findings=[Finding(statement="s", source_url="u",
        source_title="t", snippet="p", confidence=0.5)], style="brief")
    assert f.style is Style.brief
