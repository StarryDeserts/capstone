import pytest
from coo_agent.specialists.research import make_research_work
from coo_agent.schemas import ResearchRequest, ResearchDeliverable


class _StubLLM:
    def __init__(self, payload): self.payload = payload; self.calls = []
    async def generate_json(self, **kw): self.calls.append(kw); return self.payload


async def test_research_returns_findings_capped():
    payload = {"findings": [
        {"statement": f"s{i}", "source_url": f"u{i}", "source_title": f"t{i}",
         "snippet": "x", "confidence": 0.8} for i in range(5)]}
    out = await make_research_work(_StubLLM(payload))(ResearchRequest(query="q", num_sources=3))
    assert isinstance(out, ResearchDeliverable) and len(out.findings) == 3


async def test_research_uses_web_search():
    llm = _StubLLM({"findings": []})
    await make_research_work(llm)(ResearchRequest(query="q", num_sources=2))
    assert llm.calls[0]["web_search"] is True
