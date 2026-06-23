from __future__ import annotations

from ..llm import LLM
from ..schemas import Finding, ResearchDeliverable, ResearchRequest

RESEARCH_SYS = (
    "You are a research specialist. Use web search to gather factual findings for "
    "the query. For each finding return statement, source_url, source_title, snippet "
    "(a short verbatim quote), confidence (0..1), and published_at if known. "
    'Respond ONLY with JSON: {"findings": [{...}, ...]}.'
)


def make_research_work(llm: LLM):
    async def work(req: ResearchRequest) -> ResearchDeliverable:
        data = await llm.generate_json(system=RESEARCH_SYS, user=req.model_dump_json(),
                                       web_search=True)
        findings = [Finding.model_validate(f) for f in data.get("findings", [])]
        return ResearchDeliverable(findings=findings[: req.num_sources])
    return work
