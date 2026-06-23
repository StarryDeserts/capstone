import pytest
from coo_agent.specialists.format import make_format_work
from coo_agent.schemas import FormatRequest, Finding, FormatDeliverable


class _StubLLM:
    def __init__(self, payload): self.payload = payload; self.calls = []
    async def generate_json(self, **kw): self.calls.append(kw); return self.payload


async def test_format_builds_report():
    payload = {"report_markdown": "# Title\n\nbody", "references": [{"n": 1, "url": "u", "title": "t"}]}
    out = await make_format_work(_StubLLM(payload))(
        FormatRequest(title="T", verified_findings=[
            Finding(statement="s", source_url="u", source_title="t", snippet="p", confidence=0.5)],
            style="report"))
    assert isinstance(out, FormatDeliverable)
    assert out.report_markdown.startswith("# Title")
    assert out.references[0].n == 1


async def test_format_does_not_use_web_search():
    llm = _StubLLM({"report_markdown": "x", "references": []})
    await make_format_work(llm)(FormatRequest(title="T", verified_findings=[], style="brief"))
    assert llm.calls[0].get("web_search", False) is False
