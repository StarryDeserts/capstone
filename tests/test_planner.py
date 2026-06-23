import pytest
from coo_agent.planner import Planner, Plan
from coo_agent.catalog import Catalog, CatalogEntry
from coo_agent.schemas import OrchestratorRequest


def _cat():
    return Catalog({
        "research": [CatalogEntry("research", "r1", 0.05, [])],
        "verify": [CatalogEntry("verify", "v1", 0.05, [])],
        "format": [CatalogEntry("format", "f1", 0.06, [])],
    })


class _StubLLM:
    def __init__(self, queries, title="T"):
        self._q = queries; self._t = title; self.calls = []
    async def generate_json(self, **kw):
        self.calls.append(kw); return {"research_queries": self._q, "title": self._t}


async def test_deep_plan_shape():
    plan = await Planner(_StubLLM(["a", "b", "c", "d", "e"])).plan(
        OrchestratorRequest(topic="x", depth="deep", format="report"), _cat(), budget=1.0)
    assert [s.role for s in plan.steps] == ["research", "research", "research", "verify", "format"]
    assert plan.fanout == 3
    assert all(s.critical and s.group == 0 for s in plan.steps if s.role == "research")
    verify = next(s for s in plan.steps if s.role == "verify")
    assert verify.critical is False and verify.group == 1
    fmt = next(s for s in plan.steps if s.role == "format")
    assert fmt.critical is True and fmt.group == 2


async def test_quick_plan_skips_verify():
    plan = await Planner(_StubLLM(["only"])).plan(
        OrchestratorRequest(topic="x", depth="quick", format="brief"), _cat(), budget=1.0)
    assert [s.role for s in plan.steps] == ["research", "format"]


async def test_budget_caps_fanout_to_one():
    plan = await Planner(_StubLLM(["a", "b", "c"])).plan(
        OrchestratorRequest(topic="x", depth="deep", format="report"), _cat(), budget=0.12)
    assert plan.fanout == 1


async def test_llm_overproduction_capped_by_depth():
    plan = await Planner(_StubLLM(["a"] * 10)).plan(
        OrchestratorRequest(topic="x", depth="standard", format="report"), _cat(), budget=10.0)
    assert plan.fanout == 2


async def test_empty_llm_queries_falls_back_to_topic():
    plan = await Planner(_StubLLM([])).plan(
        OrchestratorRequest(topic="fallback-topic", depth="quick", format="brief"), _cat(), budget=1.0)
    research = next(s for s in plan.steps if s.role == "research")
    assert research.inputs["query"] == "fallback-topic"
