from __future__ import annotations

from ..llm import LLM
from ..schemas import FactCheckDeliverable, FactCheckRequest, VerdictItem

VERIFY_SYS = (
    "You are a fact-checking specialist. For each claim, use web search to decide a "
    "verdict: supported, contradicted, or unverifiable. Return statement, verdict, "
    "evidence_url, evidence_snippet, confidence (0..1), and optional notes. Apply the "
    'given strictness. Respond ONLY with JSON: {"verdicts": [{...}, ...]}.'
)


def make_verify_work(llm: LLM):
    async def work(req: FactCheckRequest) -> FactCheckDeliverable:
        data = await llm.generate_json(system=VERIFY_SYS, user=req.model_dump_json(),
                                       web_search=True)
        verdicts = [VerdictItem.model_validate(v) for v in data.get("verdicts", [])]
        return FactCheckDeliverable(verdicts=verdicts)
    return work
