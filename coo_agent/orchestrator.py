# coo_agent/orchestrator.py
import asyncio

from .config import Config, compute_budget
from .requester import HireResult, hire
from .schemas import (
    Citation, Claim, FactCheckDeliverable, Finding, FormatDeliverable,
    OrchestratorDeliverable, OrchestratorMeta, OrchestratorRequest,
    ResearchDeliverable, SubOrder,
)

DEFAULT_STRICTNESS = "normal"


class OrchestratorError(Exception):
    """Raised when a hard-required step (research) cannot be completed."""


def _record(sub_orders: list, role: str, r: HireResult) -> None:
    sub_orders.append(SubOrder(
        role=role, service_id=r.service_id, order_id=r.order_id or "",
        price_usdc=r.price_usdc, status=r.status))


def _build_citations(findings: list, verdicts: dict) -> list:
    out = []
    for f in findings:
        v = verdicts.get(f.statement)
        out.append(Citation(
            claim=f.statement, source_url=f.source_url, snippet=f.snippet,
            confidence=f.confidence,
            verdict=v.verdict.value if v is not None else "unverified"))
    return out


def _fallback_report(title: str, findings: list) -> str:
    lines = [f"# {title}", ""]
    lines += [f"- {f.statement} ([source]({f.source_url}))" for f in findings]
    return "\n".join(lines)


async def _hire_role(cap, catalog, role: str, inputs: dict, *, timeout: float,
                     exclude=frozenset()) -> HireResult:
    entry = catalog.select(role, exclude=exclude)
    if entry is None:
        return HireResult(False, None, None, 0.0, "", "no_candidate",
                          f"no {role} candidate")
    return await hire(cap, entry.service_id, inputs, timeout=timeout)


async def _hire_with_failover(cap, catalog, role: str, inputs: dict,
                              sub_orders: list, *, timeout: float) -> HireResult:
    first = await _hire_role(cap, catalog, role, inputs, timeout=timeout)
    _record(sub_orders, role, first)
    if first.ok or not first.service_id:
        return first
    alt = await _hire_role(cap, catalog, role, inputs, timeout=timeout,
                           exclude=frozenset({first.service_id}))
    if alt.service_id:                 # a genuine alternate existed
        _record(sub_orders, role, alt)
        return alt
    return first                       # no alternate; keep the first failure


def make_orchestrator_precheck(cap, config: Config):
    budget = compute_budget(config.orchestrator_price,
                            config.fee_rate, config.margin_floor)

    async def precheck(req) -> None:
        balance = await cap.get_balance()
        if balance < budget:
            raise OrchestratorError(
                f"insufficient working capital: have {balance}, need {budget}")

    return precheck


def make_orchestrator_work_fn(cap, catalog, planner, config: Config, *,
                              step_timeout: float = 600):
    async def work(req: OrchestratorRequest) -> OrchestratorDeliverable:
        budget = compute_budget(config.orchestrator_price,
                                config.fee_rate, config.margin_floor)
        plan = await planner.plan(req, catalog, budget)
        sub_orders: list[SubOrder] = []

        # group 0: research (parallel, with failover) — hard gate
        research_steps = [s for s in plan.steps if s.role == "research"]
        results = await asyncio.gather(*[
            _hire_with_failover(cap, catalog, "research", s.inputs,
                                sub_orders, timeout=step_timeout)
            for s in research_steps
        ])
        findings: list[Finding] = []
        for r in results:
            if r.ok and r.deliverable is not None:
                findings.extend(
                    ResearchDeliverable.model_validate(r.deliverable).findings)
        if not findings:
            raise OrchestratorError(
                "all research sub-orders failed; cannot produce report")

        # group 1: verify (best-effort)
        verdicts: dict = {}
        verify_steps = [s for s in plan.steps if s.role == "verify"]
        if verify_steps:
            strictness = verify_steps[0].inputs.get("strictness", DEFAULT_STRICTNESS)
            claims = [Claim(statement=f.statement,
                            source_url=f.source_url).model_dump()
                      for f in findings]
            vr = await _hire_with_failover(cap, catalog, "verify",
                                           {"claims": claims, "strictness": strictness},
                                           sub_orders, timeout=step_timeout)
            if vr.ok and vr.deliverable is not None:
                fcd = FactCheckDeliverable.model_validate(vr.deliverable)
                verdicts = {v.statement: v for v in fcd.verdicts}

        # group 2: format (degrade to fallback on failure)
        format_steps = [s for s in plan.steps if s.role == "format"]
        fmt_inputs = dict(format_steps[0].inputs) if format_steps else {
            "title": plan.title or req.topic,
            "style": req.format.value,
            "audience": req.audience,
        }
        fmt_inputs["verified_findings"] = [f.model_dump() for f in findings]
        title = fmt_inputs.get("title") or req.topic
        fr = await _hire_with_failover(cap, catalog, "format", fmt_inputs,
                                       sub_orders, timeout=step_timeout)
        if fr.ok and fr.deliverable is not None:
            report_md = FormatDeliverable.model_validate(fr.deliverable).report_markdown
        else:
            report_md = _fallback_report(title, findings)

        citations = _build_citations(findings, verdicts)
        total = sum(s.price_usdc for s in sub_orders if s.status == "completed")
        meta = OrchestratorMeta(sub_orders=sub_orders,
                                total_cost_usdc=total, model=config.model)
        return OrchestratorDeliverable(report_markdown=report_md,
                                       citations=citations, meta=meta)

    return work
