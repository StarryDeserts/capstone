from __future__ import annotations

from dataclasses import dataclass

from .catalog import Catalog
from .schemas import Depth, OrchestratorRequest

DEPTH_FANOUT = {Depth.quick: 1, Depth.standard: 2, Depth.deep: 3}
DEPTH_SOURCES = {Depth.quick: 3, Depth.standard: 5, Depth.deep: 8}

PLANNER_SYS = (
    "You are the planning module of a research orchestrator. Given a topic, "
    "decompose it into focused, non-overlapping web-research sub-queries. "
    'Respond ONLY with JSON: {"research_queries": [str, ...], "title": str}. '
    "Return at most the requested number of queries."
)


@dataclass
class PlanStep:
    role: str
    inputs: dict
    critical: bool
    group: int


@dataclass
class Plan:
    steps: list[PlanStep]
    fanout: int
    est_cost: float
    title: str = ""


class Planner:
    def __init__(self, llm, *, default_strictness: str = "normal"):
        self.llm = llm
        self.default_strictness = default_strictness

    async def plan(self, req: OrchestratorRequest, catalog: Catalog, budget: float) -> Plan:
        p_r = catalog.select("research", policy="cheapest").price_usdc
        p_f = catalog.select("format", policy="cheapest").price_usdc
        include_verify = req.depth in (Depth.standard, Depth.deep)
        p_v = catalog.select("verify", policy="cheapest").price_usdc if include_verify else 0.0

        depth_cap = DEPTH_FANOUT[req.depth]
        num_sources = req.max_sources or DEPTH_SOURCES[req.depth]

        proposal = await self.llm.generate_json(
            system=PLANNER_SYS,
            user=(f"topic: {req.topic}\ndepth: {req.depth.value}\n"
                  f"max sub-queries: {depth_cap}\nformat: {req.format.value}"),
        )
        queries = [q for q in (proposal.get("research_queries") or []) if isinstance(q, str)]
        if not queries:
            queries = [req.topic]
        title = proposal.get("title") or req.topic

        spare = budget - p_f - p_v
        affordable = len(queries) if p_r <= 0 else max(1, int(spare // p_r))
        n = max(1, min(len(queries), depth_cap, affordable))
        queries = queries[:n]

        steps: list[PlanStep] = []
        for q in queries:
            steps.append(PlanStep("research",
                {"query": q, "num_sources": num_sources, "recency": None, "focus": None},
                critical=True, group=0))
        if include_verify:
            strictness = "high" if req.depth is Depth.deep else self.default_strictness
            steps.append(PlanStep("verify", {"strictness": strictness}, critical=False, group=1))
        steps.append(PlanStep("format",
            {"title": title, "style": req.format.value, "audience": req.audience},
            critical=True, group=2))

        return Plan(steps=steps, fanout=n, est_cost=p_r * n + p_v + p_f, title=title)
