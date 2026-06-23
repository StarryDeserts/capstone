import pytest
from coo_agent.specialists.verify import make_verify_work
from coo_agent.schemas import FactCheckRequest, Claim, FactCheckDeliverable, Verdict


class _StubLLM:
    def __init__(self, payload): self.payload = payload; self.calls = []
    async def generate_json(self, **kw): self.calls.append(kw); return self.payload


async def test_verify_maps_verdicts():
    payload = {"verdicts": [{"statement": "s", "verdict": "supported", "evidence_url": "u",
                             "evidence_snippet": "e", "confidence": 0.9}]}
    out = await make_verify_work(_StubLLM(payload))(
        FactCheckRequest(claims=[Claim(statement="s")], strictness="high"))
    assert isinstance(out, FactCheckDeliverable)
    assert out.verdicts[0].verdict is Verdict.supported


async def test_verify_handles_empty():
    out = await make_verify_work(_StubLLM({"verdicts": []}))(
        FactCheckRequest(claims=[Claim(statement="s")], strictness="normal"))
    assert out.verdicts == []
