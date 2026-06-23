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


def make_orchestrator_work_fn(cap, catalog, planner, config: Config, *,
                              step_timeout: float = 600):
    async def work(req: OrchestratorRequest) -> OrchestratorDeliverable:
        budget = compute_budget(config.orchestrator_price,
                                config.fee_rate, config.margin_floor)
        plan = await planner.plan(req, catalog, budget)
        sub_orders: list[SubOrder] = []

        # group 0: research (parallel)
        research_steps = [s for s in plan.steps if s.role == "research"]
        results = await asyncio.gather(*[
            _hire_role(cap, catalog, "research", s.inputs, timeout=step_timeout)
            for s in research_steps
        ])
        findings: list[Finding] = []
        for r in results:
            _record(sub_orders, "research", r)
            if r.ok and r.deliverable is not None:
                findings.extend(
                    ResearchDeliverable.model_validate(r.deliverable).findings)

        # group 1: verify (optional)
        verdicts: dict = {}
        verify_steps = [s for s in plan.steps if s.role == "verify"]
        if verify_steps and findings:
            strictness = verify_steps[0].inputs.get("strictness", DEFAULT_STRICTNESS)
            claims = [Claim(statement=f.statement,
                            source_url=f.source_url).model_dump()
                      for f in findings]
            vr = await _hire_role(cap, catalog, "verify",
                                  {"claims": claims, "strictness": strictness},
                                  timeout=step_timeout)
            _record(sub_orders, "verify", vr)
            if vr.ok and vr.deliverable is not None:
                fcd = FactCheckDeliverable.model_validate(vr.deliverable)
                verdicts = {v.statement: v for v in fcd.verdicts}

        # group 2: format
        format_steps = [s for s in plan.steps if s.role == "format"]
        fmt_inputs = dict(format_steps[0].inputs) if format_steps else {
            "title": plan.title or req.topic,
            "style": req.format.value,
            "audience": req.audience,
        }
        fmt_inputs["verified_findings"] = [f.model_dump() for f in findings]
        title = fmt_inputs.get("title") or req.topic
        fr = await _hire_role(cap, catalog, "format", fmt_inputs, timeout=step_timeout)
        _record(sub_orders, "format", fr)
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
