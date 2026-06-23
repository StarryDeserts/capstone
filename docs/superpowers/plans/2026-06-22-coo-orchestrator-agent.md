# COO Orchestrator Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a CROO-listed, CAP-integrated "COO Orchestrator" agent that accepts a research goal, hires and pays specialist agents on-chain (USDC on Base), and returns a cited report.

**Architecture:** A generic provider runtime + requester helper sit over a `CapClient` *Protocol that we own*. Four agents (Orchestrator, Research, Fact-Check, Format) each run the provider runtime with a different `work_fn`; the Orchestrator's `work_fn` flips to the requester role and sub-contracts specialists. All orchestration logic is written against our own `CapClient` Protocol and tested deterministically against an in-memory `FakeCapClient` with fault injection. Only one thin adapter (`RealCapClient`) maps our Protocol onto the real `croo-sdk`, and it is the single task gated behind the live SDK spike.

**Tech Stack:** Python 3.10+ (async), `croo-sdk`, `anthropic` (Claude + web search), `pydantic` v2, `httpx`, `python-dotenv`, `PyYAML`, `pytest`, `pytest-asyncio`.

## Global Constraints

Every task's requirements implicitly include this section. Values copied verbatim from the spec.

- **Python 3.10+**, async API (croo-sdk is async).
- **Dependencies (only these):** `croo-sdk`, `anthropic`, `pydantic` (v2), `httpx`, `python-dotenv`, `PyYAML`, `pytest`, `pytest-asyncio`. No others without cause.
- **License:** MIT. Public GitHub repo (hard DQ if private).
- **Chain:** Base Mainnet, chainId **8453**, settlement in **USDC**. Gas sponsored by CROO (ERC-4337 AA); 0% gas during launch window.
- **Contracts:** CAPCore `0xaD46f1Eba2fe9cBB689D2874a52039192F2ac821`, CAPVault `0x33ECdcC8dD32330ec5a62AB1986F25ED5B5D170d`, CROOValidationModule `0xfCc7eefd6D22bC6a4F35B467928ecAF738d0B3b8`.
- **Env vars:** `CROO_API_URL`, `CROO_WS_URL`, `CROO_SDK_KEY` (per agent: `croo_sk_...`), optional `BASE_RPC_URL`, plus `ANTHROPIC_API_KEY`.
- **No programmatic service-discovery API.** Orchestrator hires from a configured `catalog.yaml` of serviceIds.
- **Demo prices:** orchestrator **0.50 USDC**; specialists **0.05–0.10 USDC** each. Margin can be ~0 (goal is volume + composability).
- **SLA:** specialists 5–10 min; orchestrator 60 min. Orchestrator SLA must exceed `parallel research(max) + verify + format + overhead`.
- **Working capital:** orchestrator AA wallet holds pre-funded USDC `>= max single-job spend`, revolving (each completed job reimburses it).
- **Registration is manual** in the dashboard (agent.croo.network); the SDK is runtime-only.
- **Secrets:** NEVER commit `.env` or any `croo_sk_` key. `.gitignore` already covers `.env` / `.env.*` (with `!.env.example`).
- **Git:** repo-local identity only (name `starrydesert`, email `86464159+StarryDeserts@users.noreply.github.com`); never `--global`. Do NOT `git push` without explicit user confirmation.
- **Anti-sybil targets:** ≥3 unique counterparty agents (3 specialists satisfy by construction), ≥5 unique buyer wallets, avoid concentrated self-trade.

## File Structure

```
coo-agent/
├─ pyproject.toml          # deps + pytest config; package = coo_agent
├─ LICENSE                 # MIT
├─ README.md               # setup, SDK methods used, integration notes, onboarding
├─ .env.example            # all env keys, no secrets
├─ catalog.yaml            # role -> [serviceIds] + price + tags + external slot
├─ Procfile                # one line per provider process (make agents)
├─ Makefile                # agents / demo / test / check targets
├─ coo_agent/
│  ├─ __init__.py
│  ├─ config.py            # env + per-agent creds, prices, caps, budget math
│  ├─ schemas.py           # pydantic Req/Deliv models for all 4 services
│  ├─ llm.py               # Claude wrapper (caching, web-search, JSON out)
│  ├─ cap_client.py        # CapClient Protocol + domain types + error helpers
│  ├─ provider_runtime.py  # generic provider loop (parse/accept/work/deliver)
│  ├─ requester.py         # generic hire helper (negotiate/pay/await/fetch)
│  ├─ catalog.py           # load/validate/select (cheapest, round-robin)
│  ├─ planner.py           # hybrid-skeleton engine -> bounded Plan
│  ├─ orchestrator.py      # orchestrator work_fn (plan -> hire -> assemble -> failover)
│  ├─ real_cap.py          # RealCapClient adapter over croo-sdk (Task 20)
│  ├─ testing/
│  │  ├─ __init__.py
│  │  └─ fake_cap.py       # FakeExchange + FakeCapClient (in-memory, fault injection)
│  └─ specialists/
│     ├─ __init__.py
│     ├─ research.py       # research work_fn
│     ├─ verify.py         # fact-check work_fn
│     └─ format.py         # format work_fn
├─ examples/
│  ├─ __init__.py
│  ├─ _bootstrap.py        # build_llm / build_cap_client / load_catalog (env-subst)
│  ├─ run_orchestrator.py  run_research.py  run_verify.py  run_format.py
│  └─ demo_client.py       # requester entrypoint for the demo
├─ scripts/
│  ├─ __init__.py
│  └─ check_balances.py    # preflight: AA wallet balances
├─ docs/superpowers/notes/
│  ├─ cap-sdk-interface.md # Phase 0 output (Task 18)
│  └─ demo-script.md       # ≤5-min demo script + submission checklist (Task 23)
└─ tests/
   ├─ conftest.py
   ├─ test_schemas.py  test_config.py  test_catalog.py  test_llm.py
   ├─ test_planner.py  test_research.py  test_verify.py  test_format.py
   ├─ test_cap_client.py  test_fake_cap.py  test_provider_runtime.py  test_requester.py
   ├─ test_orchestrator.py  test_orchestrator_resilience.py
   ├─ test_examples.py  test_scripts.py
   └─ test_real_cap.py  test_live_cap.py
```

**Milestones:**
- **A — Scaffolding + pure logic** (Tasks 1–9): no live CAP. Full TDD with stubs.
- **B — CAP abstraction + orchestration logic** (Tasks 10–15): against our own `CapClient` Protocol + `FakeCapClient`. Full TDD, no chain.
- **C — Composition roots (entrypoints) + ops glue** (Tasks 16–17): import/smoke tests.
- **D — Live CAP integration + ship-readiness** (Tasks 18–21): two **HUMAN GATES** (18 SDK spike, 19 register/fund) bracket the `RealCapClient` adapter (20) and the env-gated live smoke (21).
- **E — Ship** (Tasks 22–23): README + two-tier onboarding, demo video, BUIDL filing.

The only code task that depends on the live SDK is **Task 20 (RealCapClient)**. Everything in Milestones A–C is testable now.

---

## Milestone A — Scaffolding + pure logic

### Task 1: Project scaffolding

**Files:**
- Create: `pyproject.toml`, `LICENSE`, `.env.example`, `coo_agent/__init__.py`, `coo_agent/specialists/__init__.py`, `coo_agent/testing/__init__.py`, `tests/conftest.py`, `tests/test_smoke.py`

**Interfaces:**
- Consumes: nothing.
- Produces: an installable `coo_agent` package; `pytest` runs green.

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "coo-agent"
version = "0.1.0"
description = "COO Orchestrator Agent for the CROO Agent Hackathon"
requires-python = ">=3.10"
license = { text = "MIT" }
dependencies = [
    "croo-sdk",
    "anthropic>=0.40",
    "pydantic>=2.6",
    "httpx>=0.27",
    "python-dotenv>=1.0",
    "PyYAML>=6.0",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "pytest-asyncio>=0.23", "honcho>=1.1"]

[tool.setuptools.packages.find]
include = ["coo_agent*"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

- [ ] **Step 2: Write `LICENSE` (MIT)**

Standard MIT license text, copyright `2026 starrydesert`.

- [ ] **Step 3: Write `.env.example`**

```bash
# Anthropic
ANTHROPIC_API_KEY=sk-ant-...

# CROO platform
CROO_API_URL=https://api.croo.network
CROO_WS_URL=wss://api.croo.network/ws
BASE_RPC_URL=

# Per-agent API keys (from dashboard registration; croo_sk_...)
COO_ORCHESTRATOR_SK=croo_sk_...
RESEARCH_SK=croo_sk_...
VERIFY_SK=croo_sk_...
FORMAT_SK=croo_sk_...
DEMO_CUSTOMER_SK=croo_sk_...

# Per-agent service ids (from dashboard "Add Service")
COO_ORCHESTRATOR_SERVICE_ID=
RESEARCH_SERVICE_ID=
VERIFY_SERVICE_ID=
FORMAT_SERVICE_ID=

# Model + economics
CLAUDE_MODEL=claude-opus-4-7
PLATFORM_FEE_RATE=0.0
MARGIN_FLOOR=0.0
ORCHESTRATOR_PRICE=0.50
```

- [ ] **Step 4: Create empty `__init__.py` files**

Create `coo_agent/__init__.py`, `coo_agent/specialists/__init__.py`, `coo_agent/testing/__init__.py` (empty).

- [ ] **Step 5: Write `tests/conftest.py` and a smoke test**

`tests/conftest.py`:
```python
import pytest
```

`tests/test_smoke.py`:
```python
def test_package_imports():
    import coo_agent  # noqa: F401
```

- [ ] **Step 6: Install and run**

Run: `pip install -e ".[dev]" && pytest -q`
Expected: 1 passed. (croo-sdk install may fail offline — if so, temporarily comment it out of dependencies and note it; it is exercised live in Task 18.)

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml LICENSE .env.example coo_agent tests
git commit -m "chore: scaffold coo_agent package + pytest"
```

---

### Task 2: `schemas.py` — service Req/Deliv models

**Files:**
- Create: `coo_agent/schemas.py`
- Test: `tests/test_schemas.py`

**Interfaces:**
- Consumes: nothing.
- Produces (exact names used by every later task):
  - Enums: `Depth(quick|standard|deep)`, `Style(brief|report|bullet)`, `Strictness(low|normal|high)`, `Verdict(supported|contradicted|unverifiable)`.
  - `OrchestratorRequest(topic:str, depth:Depth, format:Style, max_sources:int|None, audience:str|None)`
  - `Finding(statement:str, source_url:str, source_title:str, snippet:str, confidence:float, published_at:str|None)`
  - `Citation(claim:str, source_url:str, snippet:str, confidence:float, verdict:Literal["supported","contradicted","unverifiable","unverified"])`
  - `SubOrder(role:str, service_id:str, order_id:str, price_usdc:float, status:str)`
  - `OrchestratorMeta(sub_orders:list[SubOrder], total_cost_usdc:float, model:str)`
  - `OrchestratorDeliverable(report_markdown:str, citations:list[Citation], meta:OrchestratorMeta)`
  - `ResearchRequest(query:str, num_sources:int, recency:str|None, focus:str|None)` / `ResearchDeliverable(findings:list[Finding])`
  - `Claim(statement:str, source_url:str|None)` / `FactCheckRequest(claims:list[Claim], strictness:Strictness)`
  - `VerdictItem(statement:str, verdict:Verdict, evidence_url:str, evidence_snippet:str, confidence:float, notes:str|None)` / `FactCheckDeliverable(verdicts:list[VerdictItem])`
  - `Reference(n:int, url:str, title:str)` / `FormatRequest(title:str, verified_findings:list[Finding], style:Style, audience:str|None)` / `FormatDeliverable(report_markdown:str, references:list[Reference])`

- [ ] **Step 1: Write the failing tests**

`tests/test_schemas.py`:
```python
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
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_schemas.py -q`
Expected: FAIL — `ModuleNotFoundError: coo_agent.schemas`.

- [ ] **Step 3: Write `coo_agent/schemas.py`**

```python
from __future__ import annotations

from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field


class Depth(str, Enum):
    quick = "quick"
    standard = "standard"
    deep = "deep"


class Style(str, Enum):
    brief = "brief"
    report = "report"
    bullet = "bullet"


class Strictness(str, Enum):
    low = "low"
    normal = "normal"
    high = "high"


class Verdict(str, Enum):
    supported = "supported"
    contradicted = "contradicted"
    unverifiable = "unverifiable"


Confidence = Field(ge=0.0, le=1.0)


class OrchestratorRequest(BaseModel):
    topic: str
    depth: Depth
    format: Style
    max_sources: Optional[int] = None
    audience: Optional[str] = None


class Finding(BaseModel):
    statement: str
    source_url: str
    source_title: str
    snippet: str
    confidence: float = Confidence
    published_at: Optional[str] = None


class Citation(BaseModel):
    claim: str
    source_url: str
    snippet: str
    confidence: float = Confidence
    verdict: Literal["supported", "contradicted", "unverifiable", "unverified"]


class SubOrder(BaseModel):
    role: str
    service_id: str
    order_id: str
    price_usdc: float
    status: str


class OrchestratorMeta(BaseModel):
    sub_orders: list[SubOrder] = []
    total_cost_usdc: float = 0.0
    model: str


class OrchestratorDeliverable(BaseModel):
    report_markdown: str
    citations: list[Citation] = []
    meta: OrchestratorMeta


class ResearchRequest(BaseModel):
    query: str
    num_sources: int = Field(ge=1)
    recency: Optional[str] = None
    focus: Optional[str] = None


class ResearchDeliverable(BaseModel):
    findings: list[Finding] = []


class Claim(BaseModel):
    statement: str
    source_url: Optional[str] = None


class FactCheckRequest(BaseModel):
    claims: list[Claim]
    strictness: Strictness = Strictness.normal


class VerdictItem(BaseModel):
    statement: str
    verdict: Verdict
    evidence_url: str = ""
    evidence_snippet: str = ""
    confidence: float = Confidence
    notes: Optional[str] = None


class FactCheckDeliverable(BaseModel):
    verdicts: list[VerdictItem] = []


class Reference(BaseModel):
    n: int
    url: str
    title: str


class FormatRequest(BaseModel):
    title: str
    verified_findings: list[Finding] = []
    style: Style
    audience: Optional[str] = None


class FormatDeliverable(BaseModel):
    report_markdown: str
    references: list[Reference] = []
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_schemas.py -q`
Expected: PASS (8 passed).

- [ ] **Step 5: Commit**

```bash
git add coo_agent/schemas.py tests/test_schemas.py
git commit -m "feat: add pydantic service schemas for all 4 CAP services"
```

---

### Task 3: `config.py` — env, per-agent creds, economics, budget math

**Files:**
- Create: `coo_agent/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `AgentCreds(name:str, sk_key:str, service_id:str)`
  - `Config(api_url:str, ws_url:str, rpc_url:str|None, anthropic_api_key:str, model:str, fee_rate:float, margin_floor:float, orchestrator_price:float, agents:dict[str,AgentCreds])` — `orchestrator_price` is the orchestrator's own listing price (env `ORCHESTRATOR_PRICE`, default `0.50`); it is the revenue side of the hiring-budget calculation.
  - `Config.from_env(env: Mapping[str,str]) -> Config` (inject a dict for testability; defaults to `os.environ`).
  - `compute_budget(price_o:float, fee_rate:float, margin_floor:float) -> float` returning `price_o*(1-fee_rate) - margin_floor`.

- [ ] **Step 1: Write the failing tests**

`tests/test_config.py`:
```python
import pytest
from coo_agent.config import Config, AgentCreds, compute_budget

BASE_ENV = {
    "ANTHROPIC_API_KEY": "sk-ant-x",
    "CROO_API_URL": "https://api.croo.network",
    "CROO_WS_URL": "wss://api.croo.network/ws",
    "CLAUDE_MODEL": "claude-opus-4-7",
    "PLATFORM_FEE_RATE": "0.1",
    "MARGIN_FLOOR": "0.0",
    "COO_ORCHESTRATOR_SK": "croo_sk_o", "COO_ORCHESTRATOR_SERVICE_ID": "svc_o",
    "RESEARCH_SK": "croo_sk_r", "RESEARCH_SERVICE_ID": "svc_r",
    "VERIFY_SK": "croo_sk_v", "VERIFY_SERVICE_ID": "svc_v",
    "FORMAT_SK": "croo_sk_f", "FORMAT_SERVICE_ID": "svc_f",
    "DEMO_CUSTOMER_SK": "croo_sk_d",
}


def test_from_env_populates_agents():
    c = Config.from_env(BASE_ENV)
    assert c.agents["research"].sk_key == "croo_sk_r"
    assert c.agents["research"].service_id == "svc_r"
    assert c.fee_rate == 0.1 and c.model == "claude-opus-4-7"
    assert c.orchestrator_price == pytest.approx(0.50)  # env default


def test_from_env_missing_required_key_raises():
    env = dict(BASE_ENV); del env["ANTHROPIC_API_KEY"]
    with pytest.raises(KeyError):
        Config.from_env(env)


def test_optional_rpc_defaults_none():
    assert Config.from_env(BASE_ENV).rpc_url is None


def test_compute_budget():
    assert compute_budget(0.50, 0.1, 0.0) == pytest.approx(0.45)
    assert compute_budget(0.50, 0.0, 0.05) == pytest.approx(0.45)
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_config.py -q`
Expected: FAIL — `ModuleNotFoundError: coo_agent.config`.

- [ ] **Step 3: Write `coo_agent/config.py`**

```python
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping, Optional

_AGENT_ENV = {
    "orchestrator": ("COO_ORCHESTRATOR_SK", "COO_ORCHESTRATOR_SERVICE_ID"),
    "research": ("RESEARCH_SK", "RESEARCH_SERVICE_ID"),
    "verify": ("VERIFY_SK", "VERIFY_SERVICE_ID"),
    "format": ("FORMAT_SK", "FORMAT_SERVICE_ID"),
    "demo_customer": ("DEMO_CUSTOMER_SK", None),
}


@dataclass(frozen=True)
class AgentCreds:
    name: str
    sk_key: str
    service_id: str


@dataclass(frozen=True)
class Config:
    api_url: str
    ws_url: str
    rpc_url: Optional[str]
    anthropic_api_key: str
    model: str
    fee_rate: float
    margin_floor: float
    orchestrator_price: float
    agents: dict[str, AgentCreds]

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> "Config":
        env = env if env is not None else os.environ
        agents: dict[str, AgentCreds] = {}
        for name, (sk_key, svc_key) in _AGENT_ENV.items():
            sk = env.get(sk_key, "")
            svc = env.get(svc_key, "") if svc_key else ""
            agents[name] = AgentCreds(name=name, sk_key=sk, service_id=svc)
        return cls(
            api_url=env["CROO_API_URL"],
            ws_url=env["CROO_WS_URL"],
            rpc_url=env.get("BASE_RPC_URL") or None,
            anthropic_api_key=env["ANTHROPIC_API_KEY"],
            model=env.get("CLAUDE_MODEL", "claude-opus-4-7"),
            fee_rate=float(env.get("PLATFORM_FEE_RATE", "0.0")),
            margin_floor=float(env.get("MARGIN_FLOOR", "0.0")),
            orchestrator_price=float(env.get("ORCHESTRATOR_PRICE", "0.50")),
            agents=agents,
        )


def compute_budget(price_o: float, fee_rate: float, margin_floor: float) -> float:
    return price_o * (1.0 - fee_rate) - margin_floor
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_config.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add coo_agent/config.py tests/test_config.py
git commit -m "feat: add config loader + budget math"
```

---

### Task 4: `catalog.py` + `catalog.yaml` — specialist catalog & selection

**Files:**
- Create: `coo_agent/catalog.py`, `catalog.yaml`
- Test: `tests/test_catalog.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `CatalogEntry(role:str, service_id:str, price_usdc:float, tags:list[str], external:bool)`
  - `Catalog` with `load(path:str) -> Catalog` (classmethod), `candidates(role:str, exclude:set[str]=()) -> list[CatalogEntry]` (own entries first, then external), `select(role:str, exclude:set[str]=(), policy:str="round_robin") -> CatalogEntry|None` (`round_robin` rotates per-role; `cheapest` picks min price). Raises `ValueError` on load if a required role (`research`,`verify`,`format`) is missing or any price < 0.

- [ ] **Step 1: Write the failing tests**

`tests/test_catalog.py`:
```python
import textwrap
import pytest
from coo_agent.catalog import Catalog, CatalogEntry


def _write(tmp_path, body):
    p = tmp_path / "catalog.yaml"
    p.write_text(textwrap.dedent(body))
    return str(p)


VALID = """
    research:
      - { service_id: r1, price_usdc: 0.05, tags: [research] }
      - { service_id: r2, price_usdc: 0.07, tags: [research], external: true }
    verify:
      - { service_id: v1, price_usdc: 0.05, tags: [verification] }
    format:
      - { service_id: f1, price_usdc: 0.06, tags: [writing] }
"""


def test_load_and_candidates(tmp_path):
    cat = Catalog.load(_write(tmp_path, VALID))
    cands = cat.candidates("research")
    assert [c.service_id for c in cands] == ["r1", "r2"]
    assert cands[1].external is True


def test_load_missing_role_raises(tmp_path):
    with pytest.raises(ValueError):
        Catalog.load(_write(tmp_path, "research:\n  - { service_id: r1, price_usdc: 0.05, tags: [] }\n"))


def test_load_negative_price_raises(tmp_path):
    bad = VALID.replace("price_usdc: 0.05", "price_usdc: -1", 1)
    with pytest.raises(ValueError):
        Catalog.load(_write(tmp_path, bad))


def test_cheapest_policy(tmp_path):
    cat = Catalog.load(_write(tmp_path, VALID))
    assert cat.select("research", policy="cheapest").service_id == "r1"


def test_round_robin_rotates_and_excludes(tmp_path):
    cat = Catalog.load(_write(tmp_path, VALID))
    first = cat.select("research").service_id
    second = cat.select("research").service_id
    assert {first, second} == {"r1", "r2"}
    assert cat.select("research", exclude={"r1", "r2"}) is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_catalog.py -q`
Expected: FAIL — `ModuleNotFoundError: coo_agent.catalog`.

- [ ] **Step 3: Write `coo_agent/catalog.py`**

```python
from __future__ import annotations

from dataclasses import dataclass, field

import yaml

REQUIRED_ROLES = ("research", "verify", "format")


@dataclass
class CatalogEntry:
    role: str
    service_id: str
    price_usdc: float
    tags: list[str] = field(default_factory=list)
    external: bool = False


class Catalog:
    def __init__(self, entries: dict[str, list[CatalogEntry]]):
        self._entries = entries
        self._rr: dict[str, int] = {role: 0 for role in entries}

    @classmethod
    def load(cls, path: str) -> "Catalog":
        with open(path, "r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
        entries: dict[str, list[CatalogEntry]] = {}
        for role, items in raw.items():
            parsed = []
            for it in items or []:
                price = float(it["price_usdc"])
                if price < 0:
                    raise ValueError(f"negative price for {it.get('service_id')}")
                parsed.append(CatalogEntry(role=role, service_id=it["service_id"],
                    price_usdc=price, tags=list(it.get("tags", [])),
                    external=bool(it.get("external", False))))
            # own entries first, external last (stable selection preference)
            parsed.sort(key=lambda e: e.external)
            entries[role] = parsed
        for role in REQUIRED_ROLES:
            if not entries.get(role):
                raise ValueError(f"catalog missing required role: {role}")
        return cls(entries)

    def candidates(self, role: str, exclude: set[str] = frozenset()) -> list[CatalogEntry]:
        return [e for e in self._entries.get(role, []) if e.service_id not in exclude]

    def select(self, role: str, exclude: set[str] = frozenset(),
               policy: str = "round_robin") -> "CatalogEntry | None":
        cands = self.candidates(role, exclude)
        if not cands:
            return None
        if policy == "cheapest":
            return min(cands, key=lambda e: e.price_usdc)
        idx = self._rr.get(role, 0) % len(cands)
        self._rr[role] = idx + 1
        return cands[idx]
```

- [ ] **Step 4: Write the shipped `catalog.yaml`**

```yaml
# role -> list of hireable services. Own agents first; add partner teams'
# serviceIds under any role with `external: true` to spread counterparties.
research:
  - { service_id: "${RESEARCH_SERVICE_ID}", price_usdc: 0.05, tags: [research, web-search] }
verify:
  - { service_id: "${VERIFY_SERVICE_ID}", price_usdc: 0.05, tags: [verification, fact-check] }
format:
  - { service_id: "${FORMAT_SERVICE_ID}", price_usdc: 0.06, tags: [writing, formatting] }
# external:
#   add partner serviceIds here, e.g.
#   research:
#     - { service_id: "svc_partner_xyz", price_usdc: 0.08, tags: [research], external: true }
```

Note: `${VAR}` placeholders are resolved by the loader's caller in Task 16 (entrypoints substitute env before `Catalog.load`); for unit tests we pass literal serviceIds. Add an env-substitution helper in Task 16, not here.

- [ ] **Step 5: Run to verify it passes**

Run: `pytest tests/test_catalog.py -q`
Expected: PASS (5 passed).

- [ ] **Step 6: Commit**

```bash
git add coo_agent/catalog.py catalog.yaml tests/test_catalog.py
git commit -m "feat: add specialist catalog with cheapest/round-robin selection"
```

---

### Task 5: `llm.py` — Claude wrapper (JSON out + web search)

**Files:**
- Create: `coo_agent/llm.py`
- Test: `tests/test_llm.py`

**Interfaces:**
- Consumes: an injected Anthropic async client (real `anthropic.AsyncAnthropic` in prod; a fake in tests).
- Produces: `LLM(client, model:str)` with `async generate_json(*, system:str, user:str, web_search:bool=False, max_tokens:int=4096) -> dict`. Raises `ValueError` if the model output is not valid JSON.

- [ ] **Step 1: Write the failing tests**

`tests/test_llm.py`:
```python
import pytest
from coo_agent.llm import LLM


class _Block:
    def __init__(self, text): self.type = "text"; self.text = text


class _Resp:
    def __init__(self, text): self.content = [_Block(text)]


class _FakeMessages:
    def __init__(self, text): self._text = text; self.calls = []
    async def create(self, **kwargs):
        self.calls.append(kwargs); return _Resp(self._text)


class _FakeClient:
    def __init__(self, text): self.messages = _FakeMessages(text)


async def test_generate_json_parses_fenced_output():
    c = _FakeClient('```json\n{"a": 1}\n```')
    out = await LLM(c, "m").generate_json(system="s", user="u")
    assert out == {"a": 1}
    assert c.messages.calls[0]["model"] == "m"


async def test_web_search_flag_adds_tools():
    c = _FakeClient('{"x": true}')
    await LLM(c, "m").generate_json(system="s", user="u", web_search=True)
    assert "tools" in c.messages.calls[0]


async def test_invalid_json_raises():
    c = _FakeClient("definitely not json")
    with pytest.raises(ValueError):
        await LLM(c, "m").generate_json(system="s", user="u")
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_llm.py -q`
Expected: FAIL — `ModuleNotFoundError: coo_agent.llm`.

- [ ] **Step 3: Write `coo_agent/llm.py`**

```python
from __future__ import annotations

import json
from typing import Any

# Anthropic server-side web search tool. Confirm the current identifier against
# Anthropic docs (use context7) at implementation time; only the wrapper changes.
WEB_SEARCH_TOOL = {"type": "web_search_20250305", "name": "web_search", "max_uses": 5}


def _extract_text(resp: Any) -> str:
    parts = []
    for block in getattr(resp, "content", []) or []:
        if getattr(block, "type", None) == "text":
            parts.append(block.text)
    return "".join(parts)


def _strip_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else ""
        if "```" in t:
            t = t[: t.rfind("```")]
    return t.strip()


class LLM:
    def __init__(self, client: Any, model: str):
        self.client = client
        self.model = model

    async def generate_json(self, *, system: str, user: str,
                            web_search: bool = False, max_tokens: int = 4096) -> dict:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        if web_search:
            kwargs["tools"] = [WEB_SEARCH_TOOL]
        resp = await self.client.messages.create(**kwargs)
        text = _strip_fences(_extract_text(resp))
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"LLM did not return valid JSON: {text[:200]!r}") from exc
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_llm.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add coo_agent/llm.py tests/test_llm.py
git commit -m "feat: add Claude JSON wrapper with web-search flag"
```

---

### Task 6: `planner.py` — hybrid-skeleton engine

**Files:**
- Create: `coo_agent/planner.py`
- Test: `tests/test_planner.py`

**Interfaces:**
- Consumes: `LLM` (or any object with `async generate_json(**kw) -> dict`), `Catalog`, `OrchestratorRequest`, `compute_budget`'s output (a float `budget`).
- Produces:
  - `PlanStep(role:str, inputs:dict, critical:bool, group:int)`
  - `Plan(steps:list[PlanStep], fanout:int, est_cost:float, title:str)`
  - `Planner(llm, *, default_strictness:str="normal")` with `async plan(req:OrchestratorRequest, catalog:Catalog, budget:float) -> Plan`.
- Rules (enforced regardless of LLM output): skeleton research→verify→format; research steps `group=0` (parallel) and `critical=True`; verify included only for `standard`/`deep` depth, `group=1`, `critical=False`; format `group=2`, `critical=True`. Fan-out `n = min(len(queries), depth_cap, budget_affordable)`, always ≥1. `depth_cap`: quick=1, standard=2, deep=3.

- [ ] **Step 1: Write the failing tests**

`tests/test_planner.py`:
```python
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
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_planner.py -q`
Expected: FAIL — `ModuleNotFoundError: coo_agent.planner`.

- [ ] **Step 3: Write `coo_agent/planner.py`**

```python
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
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_planner.py -q`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add coo_agent/planner.py tests/test_planner.py
git commit -m "feat: add hybrid-skeleton planner with budget/fan-out caps"
```

---

### Task 7: `specialists/research.py` — research work_fn

**Files:**
- Create: `coo_agent/specialists/research.py`
- Test: `tests/test_research.py`

**Interfaces:**
- Consumes: `LLM`, `ResearchRequest`, `Finding`, `ResearchDeliverable`.
- Produces: `make_research_work(llm) -> Callable[[ResearchRequest], Awaitable[ResearchDeliverable]]`. Caps findings at `req.num_sources`; calls the model with `web_search=True`.

- [ ] **Step 1: Write the failing tests**

`tests/test_research.py`:
```python
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
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_research.py -q`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Write `coo_agent/specialists/research.py`**

```python
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
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_research.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add coo_agent/specialists/research.py tests/test_research.py
git commit -m "feat: add research specialist work_fn"
```

---

### Task 8: `specialists/verify.py` — fact-check work_fn

**Files:**
- Create: `coo_agent/specialists/verify.py`
- Test: `tests/test_verify.py`

**Interfaces:**
- Consumes: `LLM`, `FactCheckRequest`, `VerdictItem`, `FactCheckDeliverable`.
- Produces: `make_verify_work(llm) -> Callable[[FactCheckRequest], Awaitable[FactCheckDeliverable]]`. Calls the model with `web_search=True`.

- [ ] **Step 1: Write the failing tests**

`tests/test_verify.py`:
```python
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
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_verify.py -q`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Write `coo_agent/specialists/verify.py`**

```python
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
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_verify.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add coo_agent/specialists/verify.py tests/test_verify.py
git commit -m "feat: add fact-check specialist work_fn"
```

---

### Task 9: `specialists/format.py` — format work_fn

**Files:**
- Create: `coo_agent/specialists/format.py`
- Test: `tests/test_format.py`

**Interfaces:**
- Consumes: `LLM`, `FormatRequest`, `Reference`, `FormatDeliverable`.
- Produces: `make_format_work(llm) -> Callable[[FormatRequest], Awaitable[FormatDeliverable]]`. No web search (pure writing).

- [ ] **Step 1: Write the failing tests**

`tests/test_format.py`:
```python
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
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_format.py -q`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Write `coo_agent/specialists/format.py`**

```python
from __future__ import annotations

from ..llm import LLM
from ..schemas import FormatDeliverable, FormatRequest, Reference

FORMAT_SYS = (
    "You are a writing specialist. Given verified findings, produce a polished, "
    "well-structured report in markdown in the requested style and for the given "
    "audience. Use numbered references and cite them inline as [n]. "
    'Respond ONLY with JSON: {"report_markdown": str, "references": [{"n": int, '
    '"url": str, "title": str}, ...]}.'
)


def make_format_work(llm: LLM):
    async def work(req: FormatRequest) -> FormatDeliverable:
        data = await llm.generate_json(system=FORMAT_SYS, user=req.model_dump_json())
        return FormatDeliverable(
            report_markdown=data.get("report_markdown", ""),
            references=[Reference.model_validate(r) for r in data.get("references", [])])
    return work
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_format.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add coo_agent/specialists/format.py tests/test_format.py
git commit -m "feat: add format specialist work_fn"
```

---

## Milestone B — CAP abstraction + orchestration logic

> All of Milestone B is written against **our own** `CapClient` Protocol and tested against `FakeCapClient`. No live SDK, no chain. The real adapter is Task 20 (post-gate).

### Task 10: `cap_client.py` — `CapClient` Protocol, domain types, error helpers

**Files:**
- Create: `coo_agent/cap_client.py`
- Test: `tests/test_cap_client.py`

**Interfaces:**
- Consumes: nothing.
- Produces (the contract every CAP-touching module depends on):
  - `OrderStatus(created|paid|completed|rejected|expired)`, `CapEvent(NEGOTIATION_CREATED|NEGOTIATION_REJECTED|NEGOTIATION_EXPIRED|ORDER_CREATED|ORDER_PAID|ORDER_COMPLETED|ORDER_REJECTED|ORDER_EXPIRED)`.
  - `Negotiation(negotiation_id:str, service_id:str, requester_did:str, requirements:dict)`
  - `Order(order_id:str, service_id:str, status:OrderStatus, price_usdc:float, requirements:dict, negotiation_id:str|None)`
  - `Delivery(order_id:str, deliverable:dict, file_url:str|None)`
  - `CapError(Exception)` with `.code`; predicates `is_insufficient_balance(e)`, `is_invalid_status(e)`, `is_not_found(e)`.
  - `CapClient` Protocol (async). **Providers** use `on(event, handler)` + `run_forever()`. **Requesters** use `negotiate_order` → `await_order_created` → `pay_order` → `await_completion` → `get_delivery`. (The await split lets the real adapter buffer the WS stream and lets the fake be race-free.)

- [ ] **Step 1: Write the failing tests**

`tests/test_cap_client.py`:
```python
from coo_agent.cap_client import (
    CapError, is_insufficient_balance, is_invalid_status, is_not_found,
    OrderStatus, CapEvent, Order, Negotiation, Delivery, CapClient,
)


def test_error_helpers_classify_by_code():
    assert is_insufficient_balance(CapError("x", code="insufficient_balance"))
    assert not is_insufficient_balance(CapError("x", code="other"))
    assert is_invalid_status(CapError("x", code="invalid_status"))
    assert is_not_found(CapError("x", code="not_found"))
    assert not is_not_found(ValueError("x"))


def test_enum_values():
    assert OrderStatus.paid.value == "paid"
    assert CapEvent.ORDER_COMPLETED.value == "ORDER_COMPLETED"


def test_domain_types_construct():
    o = Order(order_id="o", service_id="s", status=OrderStatus.created,
              price_usdc=0.1, requirements={}, negotiation_id="n")
    assert o.status is OrderStatus.created
    assert Negotiation("n", "s", "did", {}).service_id == "s"
    assert Delivery("o", {"a": 1}).deliverable == {"a": 1}


def test_protocol_is_importable():
    assert CapClient is not None
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_cap_client.py -q`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Write `coo_agent/cap_client.py`**

```python
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Awaitable, Callable, Optional, Protocol


class OrderStatus(str, Enum):
    created = "created"
    paid = "paid"
    completed = "completed"
    rejected = "rejected"
    expired = "expired"


class CapEvent(str, Enum):
    NEGOTIATION_CREATED = "NEGOTIATION_CREATED"
    NEGOTIATION_REJECTED = "NEGOTIATION_REJECTED"
    NEGOTIATION_EXPIRED = "NEGOTIATION_EXPIRED"
    ORDER_CREATED = "ORDER_CREATED"
    ORDER_PAID = "ORDER_PAID"
    ORDER_COMPLETED = "ORDER_COMPLETED"
    ORDER_REJECTED = "ORDER_REJECTED"
    ORDER_EXPIRED = "ORDER_EXPIRED"


@dataclass
class Negotiation:
    negotiation_id: str
    service_id: str
    requester_did: str
    requirements: dict


@dataclass
class Order:
    order_id: str
    service_id: str
    status: OrderStatus
    price_usdc: float
    requirements: dict
    negotiation_id: Optional[str] = None


@dataclass
class Delivery:
    order_id: str
    deliverable: dict
    file_url: Optional[str] = None


class CapError(Exception):
    def __init__(self, message: str, code: Optional[str] = None):
        super().__init__(message)
        self.code = code


def is_insufficient_balance(e: Exception) -> bool:
    return isinstance(e, CapError) and e.code == "insufficient_balance"


def is_invalid_status(e: Exception) -> bool:
    return isinstance(e, CapError) and e.code == "invalid_status"


def is_not_found(e: Exception) -> bool:
    return isinstance(e, CapError) and e.code == "not_found"


Handler = Callable[[object], Awaitable[None]]


class CapClient(Protocol):
    # lifecycle
    async def connect(self) -> None: ...
    async def close(self) -> None: ...
    async def run_forever(self) -> None: ...
    def on(self, event: CapEvent, handler: Handler) -> None: ...
    # requester
    async def negotiate_order(self, service_id: str, requirements: dict) -> Negotiation: ...
    async def await_order_created(self, negotiation_id: str, timeout: float) -> Order: ...
    async def pay_order(self, order_id: str) -> None: ...
    async def await_completion(self, order_id: str, timeout: float) -> Order: ...
    async def get_delivery(self, order_id: str) -> Delivery: ...
    async def get_download_url(self, file_id: str) -> str: ...
    # provider
    async def get_negotiation(self, negotiation_id: str) -> Negotiation: ...
    async def accept_negotiation(self, negotiation_id: str,
                                 fund_address: Optional[str] = None) -> Order: ...
    async def reject_negotiation(self, negotiation_id: str, reason: str = "") -> None: ...
    async def deliver_order(self, order_id: str, deliverable: dict,
                            file_url: Optional[str] = None) -> None: ...
    async def reject_order(self, order_id: str, reason: str = "") -> None: ...
    async def upload_file(self, content: bytes, filename: str) -> str: ...
    # both
    async def get_order(self, order_id: str) -> Order: ...
    async def list_orders(self) -> list[Order]: ...
    async def list_negotiations(self) -> list[Negotiation]: ...
    async def get_balance(self, address: Optional[str] = None) -> float: ...
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_cap_client.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add coo_agent/cap_client.py tests/test_cap_client.py
git commit -m "feat: define CapClient Protocol, domain types, error helpers"
```

---

### Task 11: `testing/fake_cap.py` — in-memory exchange with fault injection

**Files:**
- Create: `coo_agent/testing/fake_cap.py`
- Test: `tests/test_fake_cap.py`

**Interfaces:**
- Consumes: everything from `cap_client`.
- Produces:
  - `Fault(reject_negotiation:bool=False, silent_on_pay:bool=False)`
  - `FakeExchange(fee_rate:float=0.0)` with `credit(agent_id, amount)`, `register_service(service_id, provider, price)`, and async `expire_order(order_id)`. Holds `clients`, `orders`, `escrow`, `balances`.
  - `FakeCapClient(exchange, agent_id, serves:list[tuple[str,float]]=(), fault:Fault|None=None)` — implements `CapClient`. Providers register a `Fault`. Events to the **provider** are dispatched inline through `on()` handlers; events to the **requester** land in a per-client ready/waiter map so `await_order_created`/`await_completion` are race-free. `pay_order` moves USDC into escrow (raises `insufficient_balance`); `deliver_order` settles `price*(1-fee)` to the provider; `reject_order`/`expire_order` refund the requester.

- [ ] **Step 1: Write the failing tests**

`tests/test_fake_cap.py`:
```python
import pytest
from coo_agent.cap_client import CapError, CapEvent, OrderStatus, is_insufficient_balance
from coo_agent.testing.fake_cap import FakeExchange, FakeCapClient, Fault


def _wire_provider(client, service_id, deliverable):
    async def on_neg(neg):
        if neg.service_id == service_id:
            await client.accept_negotiation(neg.negotiation_id)
    async def on_paid(order):
        if order.service_id == service_id:
            await client.deliver_order(order.order_id, deliverable)
    client.on(CapEvent.NEGOTIATION_CREATED, on_neg)
    client.on(CapEvent.ORDER_PAID, on_paid)


async def test_happy_order_settles_balances():
    ex = FakeExchange(fee_rate=0.1)
    prov = FakeCapClient(ex, "prov", serves=[("svc", 0.10)])
    req = FakeCapClient(ex, "req")
    ex.credit("req", 1.0)
    _wire_provider(prov, "svc", {"ok": True})
    neg = await req.negotiate_order("svc", {"x": 1})
    order = await req.await_order_created(neg.negotiation_id, timeout=1)
    await req.pay_order(order.order_id)
    final = await req.await_completion(order.order_id, timeout=1)
    assert final.status is OrderStatus.completed
    assert (await req.get_delivery(order.order_id)).deliverable == {"ok": True}
    assert await req.get_balance() == pytest.approx(0.90)
    assert await prov.get_balance() == pytest.approx(0.09)


async def test_insufficient_balance():
    ex = FakeExchange()
    prov = FakeCapClient(ex, "prov", serves=[("svc", 0.10)])
    _wire_provider(prov, "svc", {})
    req = FakeCapClient(ex, "req")  # no funds
    neg = await req.negotiate_order("svc", {})
    order = await req.await_order_created(neg.negotiation_id, timeout=1)
    with pytest.raises(CapError) as ei:
        await req.pay_order(order.order_id)
    assert is_insufficient_balance(ei.value)


async def test_reject_negotiation_fault():
    ex = FakeExchange()
    FakeCapClient(ex, "prov", serves=[("svc", 0.10)], fault=Fault(reject_negotiation=True))
    req = FakeCapClient(ex, "req"); ex.credit("req", 1.0)
    neg = await req.negotiate_order("svc", {})
    with pytest.raises(CapError):
        await req.await_order_created(neg.negotiation_id, timeout=1)


async def test_silent_provider_times_out_and_refunds():
    ex = FakeExchange()
    prov = FakeCapClient(ex, "prov", serves=[("svc", 0.10)], fault=Fault(silent_on_pay=True))
    async def on_neg(neg):
        await prov.accept_negotiation(neg.negotiation_id)
    prov.on(CapEvent.NEGOTIATION_CREATED, on_neg)
    req = FakeCapClient(ex, "req"); ex.credit("req", 1.0)
    neg = await req.negotiate_order("svc", {})
    order = await req.await_order_created(neg.negotiation_id, timeout=1)
    await req.pay_order(order.order_id)
    with pytest.raises(CapError):
        await req.await_completion(order.order_id, timeout=0.05)
    assert await req.get_balance() == pytest.approx(1.0)  # refunded


async def test_reject_order_refunds_requester():
    ex = FakeExchange()
    prov = FakeCapClient(ex, "prov", serves=[("svc", 0.10)])
    async def on_neg(neg): await prov.accept_negotiation(neg.negotiation_id)
    async def on_paid(order): await prov.reject_order(order.order_id, "nope")
    prov.on(CapEvent.NEGOTIATION_CREATED, on_neg)
    prov.on(CapEvent.ORDER_PAID, on_paid)
    req = FakeCapClient(ex, "req"); ex.credit("req", 1.0)
    neg = await req.negotiate_order("svc", {})
    order = await req.await_order_created(neg.negotiation_id, timeout=1)
    await req.pay_order(order.order_id)
    final = await req.await_completion(order.order_id, timeout=1)
    assert final.status is OrderStatus.rejected
    assert await req.get_balance() == pytest.approx(1.0)
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_fake_cap.py -q`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Write `coo_agent/testing/fake_cap.py`**

```python
from __future__ import annotations

import asyncio
import itertools
from dataclasses import dataclass
from typing import Optional

from ..cap_client import (
    CapError, CapEvent, Delivery, Handler, Negotiation, Order, OrderStatus,
)

_ids = itertools.count(1)


@dataclass
class Fault:
    reject_negotiation: bool = False
    silent_on_pay: bool = False


class FakeExchange:
    def __init__(self, fee_rate: float = 0.0):
        self.fee_rate = fee_rate
        self.clients: dict[str, "FakeCapClient"] = {}
        self.providers: dict[str, "FakeCapClient"] = {}
        self.price_by_service: dict[str, float] = {}
        self.negotiations: dict[str, Negotiation] = {}
        self.orders: dict[str, Order] = {}
        self.deliveries: dict[str, Delivery] = {}
        self.balances: dict[str, float] = {}
        self.escrow: dict[str, float] = {}
        self.requester_by_order: dict[str, str] = {}
        self.requester_by_neg: dict[str, str] = {}

    def credit(self, agent_id: str, amount: float) -> None:
        self.balances[agent_id] = self.balances.get(agent_id, 0.0) + amount

    def register_service(self, service_id: str, provider: "FakeCapClient", price: float) -> None:
        self.providers[service_id] = provider
        self.price_by_service[service_id] = price

    async def expire_order(self, order_id: str) -> None:
        order = self.orders.get(order_id)
        if order is None or order.status is not OrderStatus.paid:
            return
        order.status = OrderStatus.expired
        amount = self.escrow.pop(order_id, 0.0)
        requester = self.requester_by_order[order_id]
        self.credit(requester, amount)
        self.clients[requester]._push(CapEvent.ORDER_EXPIRED, order)


class FakeCapClient:
    def __init__(self, exchange: FakeExchange, agent_id: str,
                 serves: list[tuple[str, float]] = (), fault: Optional[Fault] = None):
        self.ex = exchange
        self.agent_id = agent_id
        self.fault = fault or Fault()
        self._handlers: dict[CapEvent, list[Handler]] = {}
        self._ready: dict[tuple, tuple] = {}
        self._waiters: dict[tuple, asyncio.Future] = {}
        exchange.clients[agent_id] = self
        for service_id, price in serves:
            exchange.register_service(service_id, self, price)

    # ---- lifecycle ----
    async def connect(self) -> None: ...
    async def close(self) -> None: ...
    async def run_forever(self) -> None:
        await asyncio.Event().wait()  # block; tests don't call this

    def on(self, event: CapEvent, handler: Handler) -> None:
        self._handlers.setdefault(event, []).append(handler)

    # ---- internal delivery ----
    async def _dispatch(self, event: CapEvent, payload) -> None:
        for handler in list(self._handlers.get(event, [])):
            await handler(payload)

    @staticmethod
    def _key(event: CapEvent, payload) -> tuple:
        if event in (CapEvent.ORDER_CREATED, CapEvent.NEGOTIATION_REJECTED,
                     CapEvent.NEGOTIATION_EXPIRED):
            nid = getattr(payload, "negotiation_id", None)
            return ("neg", nid)
        return ("order", payload.order_id)

    def _push(self, event: CapEvent, payload) -> None:
        key = self._key(event, payload)
        fut = self._waiters.pop(key, None)
        if fut is not None and not fut.done():
            fut.set_result((event, payload))
        else:
            self._ready[key] = (event, payload)

    async def _wait_key(self, key: tuple, timeout: float) -> tuple:
        if key in self._ready:
            return self._ready.pop(key)
        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        self._waiters[key] = fut
        try:
            return await asyncio.wait_for(fut, timeout)
        except asyncio.TimeoutError as exc:
            self._waiters.pop(key, None)
            raise CapError("timeout", code="timeout") from exc

    # ---- requester ----
    async def negotiate_order(self, service_id: str, requirements: dict) -> Negotiation:
        provider = self.ex.providers.get(service_id)
        if provider is None:
            raise CapError(f"no service {service_id}", code="not_found")
        nid = f"neg_{next(_ids)}"
        neg = Negotiation(nid, service_id, requester_did=self.agent_id, requirements=requirements)
        self.ex.negotiations[nid] = neg
        self.ex.requester_by_neg[nid] = self.agent_id
        if provider.fault.reject_negotiation:
            self._push(CapEvent.NEGOTIATION_REJECTED, neg)
        else:
            await provider._dispatch(CapEvent.NEGOTIATION_CREATED, neg)
        return neg

    async def await_order_created(self, negotiation_id: str, timeout: float) -> Order:
        event, payload = await self._wait_key(("neg", negotiation_id), timeout)
        if event is CapEvent.ORDER_CREATED:
            return payload
        raise CapError("negotiation rejected", code="rejected")

    async def pay_order(self, order_id: str) -> None:
        order = self.ex.orders[order_id]
        if order.status is not OrderStatus.created:
            raise CapError("not payable", code="invalid_status")
        price = order.price_usdc
        if self.ex.balances.get(self.agent_id, 0.0) < price:
            raise CapError("insufficient balance", code="insufficient_balance")
        self.ex.balances[self.agent_id] -= price
        self.ex.escrow[order_id] = price
        order.status = OrderStatus.paid
        provider = self.ex.providers[order.service_id]
        if not provider.fault.silent_on_pay:
            await provider._dispatch(CapEvent.ORDER_PAID, order)

    async def await_completion(self, order_id: str, timeout: float) -> Order:
        try:
            _event, payload = await self._wait_key(("order", order_id), timeout)
            return payload
        except CapError as exc:
            if exc.code == "timeout":
                await self.ex.expire_order(order_id)
            raise

    async def get_delivery(self, order_id: str) -> Delivery:
        d = self.ex.deliveries.get(order_id)
        if d is None:
            raise CapError("no delivery", code="not_found")
        return d

    async def get_download_url(self, file_id: str) -> str:
        return f"fake://file/{file_id}"

    # ---- provider ----
    async def get_negotiation(self, negotiation_id: str) -> Negotiation:
        return self.ex.negotiations[negotiation_id]

    async def accept_negotiation(self, negotiation_id: str,
                                 fund_address: Optional[str] = None) -> Order:
        neg = self.ex.negotiations[negotiation_id]
        oid = f"ord_{next(_ids)}"
        order = Order(oid, neg.service_id, OrderStatus.created,
                      self.ex.price_by_service[neg.service_id], neg.requirements, negotiation_id)
        self.ex.orders[oid] = order
        requester = self.ex.requester_by_neg[negotiation_id]
        self.ex.requester_by_order[oid] = requester
        self.ex.clients[requester]._push(CapEvent.ORDER_CREATED, order)
        return order

    async def reject_negotiation(self, negotiation_id: str, reason: str = "") -> None:
        neg = self.ex.negotiations[negotiation_id]
        requester = self.ex.requester_by_neg[negotiation_id]
        self.ex.clients[requester]._push(CapEvent.NEGOTIATION_REJECTED, neg)

    async def deliver_order(self, order_id: str, deliverable: dict,
                            file_url: Optional[str] = None) -> None:
        order = self.ex.orders[order_id]
        if order.status is not OrderStatus.paid:
            raise CapError("not deliverable", code="invalid_status")
        order.status = OrderStatus.completed
        self.ex.deliveries[order_id] = Delivery(order_id, deliverable, file_url)
        amount = self.ex.escrow.pop(order_id, 0.0)
        self.ex.credit(self.agent_id, amount * (1.0 - self.ex.fee_rate))
        requester = self.ex.requester_by_order[order_id]
        self.ex.clients[requester]._push(CapEvent.ORDER_COMPLETED, order)

    async def reject_order(self, order_id: str, reason: str = "") -> None:
        order = self.ex.orders[order_id]
        order.status = OrderStatus.rejected
        amount = self.ex.escrow.pop(order_id, 0.0)
        requester = self.ex.requester_by_order[order_id]
        self.ex.credit(requester, amount)
        self.ex.clients[requester]._push(CapEvent.ORDER_REJECTED, order)

    async def upload_file(self, content: bytes, filename: str) -> str:
        return f"fake://upload/{filename}"

    # ---- both ----
    async def get_order(self, order_id: str) -> Order:
        return self.ex.orders[order_id]

    async def list_orders(self) -> list[Order]:
        return list(self.ex.orders.values())

    async def list_negotiations(self) -> list[Negotiation]:
        return list(self.ex.negotiations.values())

    async def get_balance(self, address: Optional[str] = None) -> float:
        return self.ex.balances.get(self.agent_id, 0.0)
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_fake_cap.py -q`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add coo_agent/testing/fake_cap.py tests/test_fake_cap.py
git commit -m "test: add in-memory FakeCapClient exchange with fault injection"
```

---

### Task 12: Generic Provider Runtime

**Files:**
- Create: `coo_agent/provider_runtime.py`
- Test: `tests/test_provider_runtime.py`

**Interfaces:**
- Consumes: `CapClient` Protocol (`on`, `accept_negotiation`, `reject_negotiation`, `deliver_order`, `reject_order`, `upload_file`, `connect`, `run_forever`) and domain types `Negotiation`, `Order`, `CapEvent` from Task 10; `FakeExchange`, `FakeCapClient`, `Fault` from Task 11 (tests only). A `parse_fn(dict) -> model` and `async work_fn(model) -> deliverable_model` whose concrete forms come from the specialists (Tasks 7-9) and orchestrator (Task 14).
- Produces: `ProviderRuntime(cap, service_id, parse_fn, work_fn, *, precheck_fn=None, fund_address=None, upload_threshold=200_000)` exposing `.install()` (register handlers) and `async .run()` (install + connect + run_forever). The work-failure path calls `reject_order`, which refunds the requester. Consumed by the entrypoints (Task 16) and orchestrator wiring (Tasks 14-15). `precheck_fn` is the hook the orchestrator uses for its working-capital affordability check (Task 15).

The runtime is stateless across events: both handlers re-parse `requirements` from their own event payload, so concurrent orders and fresh processes need no shared state. A bad request schema rejects the *negotiation* (no funds moved); a `work_fn` exception or oversized/serialization failure rejects the *paid order* (funds refunded).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_provider_runtime.py
import pytest
from pydantic import BaseModel

from coo_agent.cap_client import OrderStatus, CapError
from coo_agent.provider_runtime import ProviderRuntime
from coo_agent.testing.fake_cap import FakeExchange, FakeCapClient, Fault


class Req(BaseModel):
    text: str


class Deliv(BaseModel):
    echoed: str


SERVICE = "svc_echo"


def parse(requirements: dict) -> Req:
    return Req.model_validate(requirements)


def make_work(calls):
    async def work(req: Req) -> Deliv:
        calls.append(req.text)
        return Deliv(echoed=req.text.upper())
    return work


@pytest.fixture
def wired():
    ex = FakeExchange(fee_rate=0.1)
    provider = FakeCapClient(ex, "provider", serves=[(SERVICE, 0.05)])
    requester = FakeCapClient(ex, "requester")
    ex.credit("requester", 1.0)
    return ex, provider, requester


async def test_happy_path_delivers_and_settles(wired):
    ex, provider, requester = wired
    calls = []
    ProviderRuntime(provider, SERVICE, parse, make_work(calls)).install()

    neg = await requester.negotiate_order(SERVICE, {"text": "hello"})
    order = await requester.await_order_created(neg.negotiation_id, timeout=1)
    await requester.pay_order(order.order_id)
    completed = await requester.await_completion(order.order_id, timeout=1)
    delivery = await requester.get_delivery(order.order_id)

    assert calls == ["hello"]
    assert completed.status is OrderStatus.completed
    assert delivery.deliverable == {"echoed": "HELLO"}
    assert ex.balances["requester"] == pytest.approx(0.95)
    assert ex.balances["provider"] == pytest.approx(0.045)


async def test_invalid_requirements_rejects_negotiation(wired):
    ex, provider, requester = wired
    ProviderRuntime(provider, SERVICE, parse, make_work([])).install()

    neg = await requester.negotiate_order(SERVICE, {"wrong": "field"})
    with pytest.raises(CapError) as ei:
        await requester.await_order_created(neg.negotiation_id, timeout=1)
    assert ei.value.code == "rejected"
    assert ex.balances["requester"] == pytest.approx(1.0)


async def test_work_failure_rejects_order_and_refunds(wired):
    ex, provider, requester = wired

    async def boom(req: Req) -> Deliv:
        raise RuntimeError("model exploded")

    ProviderRuntime(provider, SERVICE, parse, boom).install()

    neg = await requester.negotiate_order(SERVICE, {"text": "hi"})
    order = await requester.await_order_created(neg.negotiation_id, timeout=1)
    await requester.pay_order(order.order_id)
    completed = await requester.await_completion(order.order_id, timeout=1)

    assert completed.status is OrderStatus.rejected
    assert ex.balances["requester"] == pytest.approx(1.0)
    assert ex.balances.get("provider", 0.0) == pytest.approx(0.0)


async def test_large_deliverable_is_uploaded(wired):
    ex, provider, requester = wired

    async def big(req: Req) -> Deliv:
        return Deliv(echoed="x" * 1000)

    ProviderRuntime(provider, SERVICE, parse, big, upload_threshold=100).install()

    neg = await requester.negotiate_order(SERVICE, {"text": "hi"})
    order = await requester.await_order_created(neg.negotiation_id, timeout=1)
    await requester.pay_order(order.order_id)
    await requester.await_completion(order.order_id, timeout=1)
    delivery = await requester.get_delivery(order.order_id)

    assert delivery.file_url is not None
    assert delivery.file_url.startswith("fake://upload/")


async def test_precheck_rejects_negotiation(wired):
    ex, provider, requester = wired

    async def precheck(req: Req) -> None:
        raise RuntimeError("cannot afford")

    ProviderRuntime(provider, SERVICE, parse, make_work([]),
                    precheck_fn=precheck).install()

    neg = await requester.negotiate_order(SERVICE, {"text": "hi"})
    with pytest.raises(CapError) as ei:
        await requester.await_order_created(neg.negotiation_id, timeout=1)
    assert ei.value.code == "rejected"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_provider_runtime.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'coo_agent.provider_runtime'`.

- [ ] **Step 3: Write minimal implementation**

```python
# coo_agent/provider_runtime.py
from typing import Any, Awaitable, Callable, Optional

from .cap_client import CapClient, CapEvent, Negotiation, Order

ParseFn = Callable[[dict], Any]
WorkFn = Callable[[Any], Awaitable[Any]]
PrecheckFn = Callable[[Any], Awaitable[None]]


class ProviderRuntime:
    def __init__(self, cap: CapClient, service_id: str,
                 parse_fn: ParseFn, work_fn: WorkFn, *,
                 precheck_fn: Optional[PrecheckFn] = None,
                 fund_address: Optional[str] = None,
                 upload_threshold: int = 200_000):
        self.cap = cap
        self.service_id = service_id
        self.parse_fn = parse_fn
        self.work_fn = work_fn
        self.precheck_fn = precheck_fn
        self.fund_address = fund_address
        self.upload_threshold = upload_threshold

    def install(self) -> None:
        self.cap.on(CapEvent.NEGOTIATION_CREATED, self._on_negotiation)
        self.cap.on(CapEvent.ORDER_PAID, self._on_paid)

    async def run(self) -> None:
        self.install()
        await self.cap.connect()
        await self.cap.run_forever()

    async def _on_negotiation(self, neg: Negotiation) -> None:
        if neg.service_id != self.service_id:
            return
        try:
            req = self.parse_fn(neg.requirements)
        except Exception as exc:
            await self.cap.reject_negotiation(
                neg.negotiation_id, reason=f"invalid request: {exc}")
            return
        if self.precheck_fn is not None:
            try:
                await self.precheck_fn(req)
            except Exception as exc:
                await self.cap.reject_negotiation(
                    neg.negotiation_id, reason=str(exc))
                return
        await self.cap.accept_negotiation(
            neg.negotiation_id, fund_address=self.fund_address)

    async def _on_paid(self, order: Order) -> None:
        if order.service_id != self.service_id:
            return
        try:
            req = self.parse_fn(order.requirements)
            deliverable = await self.work_fn(req)
            payload = deliverable.model_dump(mode="json")
            body = deliverable.model_dump_json().encode("utf-8")
            file_url = None
            if len(body) > self.upload_threshold:
                file_url = await self.cap.upload_file(
                    body, f"{order.order_id}.json")
            await self.cap.deliver_order(
                order.order_id, payload, file_url=file_url)
        except Exception as exc:
            await self.cap.reject_order(order.order_id, reason=str(exc))
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_provider_runtime.py -q`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add coo_agent/provider_runtime.py tests/test_provider_runtime.py
git commit -m "feat: add generic provider runtime (parse/accept/work/deliver)"
```

---

### Task 13: Generic Hire Helper (Requester)

**Files:**
- Create: `coo_agent/requester.py`
- Test: `tests/test_requester.py`

**Interfaces:**
- Consumes: `CapClient` Protocol requester methods (`negotiate_order`, `await_order_created`, `pay_order`, `await_completion`, `get_delivery`) plus `OrderStatus` and `CapError` from Task 10; `ProviderRuntime` (Task 12) + `FakeCapClient`/`FakeExchange`/`Fault` (Task 11) for tests.
- Produces: `HireResult(ok: bool, deliverable: Optional[dict], order_id: Optional[str], price_usdc: float, service_id: str, status: str, error: Optional[str] = None)` and `async hire(cap, service_id, requirements, *, timeout) -> HireResult`. Consumed by the orchestrator (Tasks 14-15). On any `CapError` (unknown service, negotiation rejected, timeout, insufficient balance) or a non-`completed` terminal status (rejected/expired), returns `ok=False` with `status` set to the failure code — never raises. The requester is always refunded on the failure paths by the time `hire` returns.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_requester.py
import pytest
from pydantic import BaseModel

from coo_agent.requester import hire, HireResult
from coo_agent.provider_runtime import ProviderRuntime
from coo_agent.testing.fake_cap import FakeExchange, FakeCapClient, Fault


class Req(BaseModel):
    text: str


class Deliv(BaseModel):
    echoed: str


SERVICE = "svc_echo"


def parse(requirements: dict) -> Req:
    return Req.model_validate(requirements)


async def echo_work(req: Req) -> Deliv:
    return Deliv(echoed=req.text.upper())


def _wire(fault=None, work_fn=echo_work):
    ex = FakeExchange(fee_rate=0.1)
    provider = FakeCapClient(ex, "provider", serves=[(SERVICE, 0.05)], fault=fault)
    requester = FakeCapClient(ex, "requester")
    ex.credit("requester", 1.0)
    ProviderRuntime(provider, SERVICE, parse, work_fn).install()
    return ex, requester


async def test_hire_success_returns_deliverable():
    ex, requester = _wire()
    result = await hire(requester, SERVICE, {"text": "hi"}, timeout=1)
    assert result.ok is True
    assert result.deliverable == {"echoed": "HI"}
    assert result.status == "completed"
    assert result.price_usdc == pytest.approx(0.05)
    assert result.order_id is not None
    assert result.error is None


async def test_hire_negotiation_rejected_returns_failure():
    ex, requester = _wire(fault=Fault(reject_negotiation=True))
    result = await hire(requester, SERVICE, {"text": "hi"}, timeout=1)
    assert result.ok is False
    assert result.status == "rejected"
    assert result.deliverable is None
    assert ex.balances["requester"] == pytest.approx(1.0)


async def test_hire_unknown_service_returns_failure():
    ex, requester = _wire()
    result = await hire(requester, "svc_missing", {"text": "hi"}, timeout=1)
    assert result.ok is False
    assert result.status == "not_found"
    assert result.order_id is None


async def test_hire_provider_timeout_refunds_and_fails():
    ex, requester = _wire(fault=Fault(silent_on_pay=True))
    result = await hire(requester, SERVICE, {"text": "hi"}, timeout=0.05)
    assert result.ok is False
    assert result.status == "timeout"
    assert ex.balances["requester"] == pytest.approx(1.0)


async def test_hire_work_failure_returns_rejected_and_refunds():
    async def boom(req: Req) -> Deliv:
        raise RuntimeError("nope")

    ex, requester = _wire(work_fn=boom)
    result = await hire(requester, SERVICE, {"text": "hi"}, timeout=1)
    assert result.ok is False
    assert result.status == "rejected"
    assert ex.balances["requester"] == pytest.approx(1.0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_requester.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'coo_agent.requester'`.

- [ ] **Step 3: Write minimal implementation**

```python
# coo_agent/requester.py
from dataclasses import dataclass
from typing import Optional

from .cap_client import CapClient, CapError, OrderStatus


@dataclass
class HireResult:
    ok: bool
    deliverable: Optional[dict]
    order_id: Optional[str]
    price_usdc: float
    service_id: str
    status: str
    error: Optional[str] = None


async def hire(cap: CapClient, service_id: str, requirements: dict, *,
               timeout: float) -> HireResult:
    order_id: Optional[str] = None
    price = 0.0
    try:
        neg = await cap.negotiate_order(service_id, requirements)
        order = await cap.await_order_created(neg.negotiation_id, timeout=timeout)
        order_id = order.order_id
        price = order.price_usdc
        await cap.pay_order(order.order_id)
        completed = await cap.await_completion(order.order_id, timeout=timeout)
        if completed.status is not OrderStatus.completed:
            return HireResult(False, None, order_id, price, service_id,
                              completed.status.value,
                              f"order {completed.status.value}")
        delivery = await cap.get_delivery(order.order_id)
        return HireResult(True, delivery.deliverable, order_id, price,
                          service_id, completed.status.value)
    except CapError as exc:
        return HireResult(False, None, order_id, price, service_id,
                          exc.code or "error", str(exc))
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_requester.py -q`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add coo_agent/requester.py tests/test_requester.py
git commit -m "feat: add generic hire helper returning HireResult"
```

---

### Task 14: Orchestrator `work_fn` — Happy Path

**Files:**
- Create: `coo_agent/orchestrator.py`
- Test: `tests/test_orchestrator.py`

**Interfaces:**
- Consumes: `compute_budget` + `Config` (Task 3, now carrying `orchestrator_price`); `Catalog.select` (Task 4); `hire`/`HireResult` (Task 13); schemas `OrchestratorRequest`, `OrchestratorDeliverable`, `OrchestratorMeta`, `SubOrder`, `Citation`, `Claim`, `Finding`, `ResearchDeliverable`, `FactCheckDeliverable`, `FormatDeliverable` (Task 2); a `planner` object exposing `async plan(req, catalog, budget) -> Plan` (Task 6); `ProviderRuntime` + `FakeCapClient`/`FakeExchange` (Tasks 11-12) for tests.
- Produces: `make_orchestrator_work_fn(cap, catalog, planner, config, *, step_timeout=600) -> work_fn` where `async work_fn(req: OrchestratorRequest) -> OrchestratorDeliverable`; plus module helpers `_hire_role(cap, catalog, role, inputs, *, timeout, exclude=frozenset()) -> HireResult`, `_record`, `_build_citations`, `_fallback_report`. This `work_fn` is what the orchestrator's `ProviderRuntime` runs (Task 16 wires it). Task 15 hardens it with retry/failover, working-capital precheck, and critical-failure raising.

Data flow: budget = `compute_budget(orchestrator_price, fee_rate, margin_floor)` → `planner.plan` → **group 0** research steps hired in parallel (`asyncio.gather`), findings aggregated → **group 1** verify (only if the plan has a verify step *and* there are findings): claims are built from findings, strictness read from the verify step's `inputs` → **group 2** format: the plan's format-step `inputs` (title/style/audience) are reused and `verified_findings` injected. Citations pair each finding with its verdict (`"unverified"` when no verdict exists). `total_cost_usdc` sums `completed` sub-orders only. The orchestrator is the *payer* (requester) for every sub-order, drawing on its working capital.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_orchestrator.py
import pytest

from coo_agent.catalog import Catalog
from coo_agent.config import Config
from coo_agent.orchestrator import make_orchestrator_work_fn
from coo_agent.planner import Plan, PlanStep
from coo_agent.provider_runtime import ProviderRuntime
from coo_agent.schemas import (
    Depth, FactCheckDeliverable, FactCheckRequest, Finding, FormatDeliverable,
    FormatRequest, OrchestratorRequest, Reference, ResearchDeliverable,
    ResearchRequest, Style, Verdict, VerdictItem,
)
from coo_agent.testing.fake_cap import FakeExchange, FakeCapClient


def _parse_research(d): return ResearchRequest.model_validate(d)
def _parse_verify(d): return FactCheckRequest.model_validate(d)
def _parse_format(d): return FormatRequest.model_validate(d)


async def _research_work(req: ResearchRequest) -> ResearchDeliverable:
    return ResearchDeliverable(findings=[
        Finding(statement=f"Fact {i} about {req.query}",
                source_url=f"https://ex.com/{req.query}/{i}",
                source_title=f"T{i}", snippet="snip", confidence=0.9)
        for i in range(req.num_sources)
    ])


async def _verify_work(req: FactCheckRequest) -> FactCheckDeliverable:
    return FactCheckDeliverable(verdicts=[
        VerdictItem(statement=c.statement, verdict=Verdict.supported,
                    evidence_url=c.source_url or "", confidence=0.8)
        for c in req.claims
    ])


async def _format_work(req: FormatRequest) -> FormatDeliverable:
    body = "\n".join(f"- {f.statement}" for f in req.verified_findings)
    return FormatDeliverable(
        report_markdown=f"# {req.title}\n\n{body}",
        references=[Reference(n=i + 1, url=f.source_url, title=f.source_title)
                    for i, f in enumerate(req.verified_findings)])


def _cfg():
    return Config(api_url="", ws_url="", rpc_url=None, anthropic_api_key="",
                  model="claude-opus-4-7", fee_rate=0.0, margin_floor=0.0,
                  orchestrator_price=0.50, agents={})


class StubPlanner:
    def __init__(self, steps, title="Title", fanout=1):
        self._plan = Plan(steps=steps, fanout=fanout, est_cost=0.15, title=title)

    async def plan(self, req, catalog, budget):
        return self._plan


def _build(tmp_path):
    cat_yaml = tmp_path / "catalog.yaml"
    cat_yaml.write_text(
        "research:\n  - { service_id: svc_r, price_usdc: 0.05, tags: [] }\n"
        "verify:\n  - { service_id: svc_v, price_usdc: 0.05, tags: [] }\n"
        "format:\n  - { service_id: svc_f, price_usdc: 0.05, tags: [] }\n"
    )
    catalog = Catalog.load(str(cat_yaml))
    ex = FakeExchange(fee_rate=0.0)
    r = FakeCapClient(ex, "research", serves=[("svc_r", 0.05)])
    v = FakeCapClient(ex, "verify", serves=[("svc_v", 0.05)])
    f = FakeCapClient(ex, "format", serves=[("svc_f", 0.05)])
    orch = FakeCapClient(ex, "orchestrator")
    ex.credit("orchestrator", 1.0)
    ProviderRuntime(r, "svc_r", _parse_research, _research_work).install()
    ProviderRuntime(v, "svc_v", _parse_verify, _verify_work).install()
    ProviderRuntime(f, "svc_f", _parse_format, _format_work).install()
    return ex, orch, catalog


def _fmt_step(title, style, group=2):
    return PlanStep(role="format",
                    inputs={"title": title, "style": style, "audience": None},
                    critical=True, group=group)


async def test_happy_path_assembles_report_with_citations(tmp_path):
    ex, orch, catalog = _build(tmp_path)
    steps = [
        PlanStep(role="research", inputs={"query": "X", "num_sources": 2},
                 critical=True, group=0),
        PlanStep(role="verify", inputs={"strictness": "normal"},
                 critical=False, group=1),
        _fmt_step("State of X", "report"),
    ]
    work = make_orchestrator_work_fn(
        orch, catalog, StubPlanner(steps, title="State of X"), _cfg(), step_timeout=1)
    result = await work(OrchestratorRequest(
        topic="State of X", depth=Depth.standard, format=Style.report))

    assert result.report_markdown.startswith("# State of X")
    assert [s.role for s in result.meta.sub_orders] == ["research", "verify", "format"]
    assert all(s.status == "completed" for s in result.meta.sub_orders)
    assert result.meta.total_cost_usdc == pytest.approx(0.15)
    assert result.meta.model == "claude-opus-4-7"
    assert len(result.citations) == 2
    assert all(c.verdict == "supported" for c in result.citations)
    assert ex.balances["orchestrator"] == pytest.approx(0.85)  # paid 3 x 0.05


async def test_parallel_research_aggregates_findings(tmp_path):
    ex, orch, catalog = _build(tmp_path)
    steps = [
        PlanStep(role="research", inputs={"query": "A", "num_sources": 2},
                 critical=True, group=0),
        PlanStep(role="research", inputs={"query": "B", "num_sources": 3},
                 critical=True, group=0),
        _fmt_step("T", "report"),
    ]
    work = make_orchestrator_work_fn(
        orch, catalog, StubPlanner(steps, fanout=2), _cfg(), step_timeout=1)
    result = await work(OrchestratorRequest(
        topic="T", depth=Depth.deep, format=Style.report))

    research_orders = [s for s in result.meta.sub_orders if s.role == "research"]
    assert len(research_orders) == 2
    assert len(result.citations) == 5            # 2 + 3 findings
    assert all(c.verdict == "unverified" for c in result.citations)  # no verify step


async def test_no_verify_step_marks_citations_unverified(tmp_path):
    ex, orch, catalog = _build(tmp_path)
    steps = [
        PlanStep(role="research", inputs={"query": "X", "num_sources": 1},
                 critical=True, group=0),
        _fmt_step("X", "brief"),
    ]
    work = make_orchestrator_work_fn(orch, catalog, StubPlanner(steps), _cfg(), step_timeout=1)
    result = await work(OrchestratorRequest(
        topic="X", depth=Depth.quick, format=Style.brief))

    assert len(result.citations) == 1
    assert result.citations[0].verdict == "unverified"
    assert {s.role for s in result.meta.sub_orders} == {"research", "format"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_orchestrator.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'coo_agent.orchestrator'`.

- [ ] **Step 3: Write minimal implementation**

```python
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
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_orchestrator.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add coo_agent/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: add orchestrator work_fn happy path (plan -> hire -> assemble)"
```

---

### Task 15: Orchestrator Resilience — Failover, Precheck, Critical-Failure Refund

**Files:**
- Modify: `coo_agent/orchestrator.py`
- Test: `tests/test_orchestrator_resilience.py`

**Interfaces:**
- Consumes: everything Task 14 consumed, plus `CapClient.get_balance` (Task 10) for the precheck and `Fault(reject_negotiation=True)` (Task 11) to drive failures in tests.
- Produces (added to `orchestrator.py`): `OrchestratorError(Exception)`; `_hire_with_failover(cap, catalog, role, inputs, sub_orders, *, timeout) -> HireResult` (initial hire + at most one retry on a *different* serviceId, recording each real attempt into `sub_orders`); `make_orchestrator_precheck(cap, config) -> async precheck(req)` (raises `OrchestratorError` when the orchestrator's balance is below its hiring budget — wired as the orchestrator `ProviderRuntime`'s `precheck_fn` in Task 16). `make_orchestrator_work_fn` is updated to hire every role through `_hire_with_failover`, **raise `OrchestratorError` when research yields zero findings** (the hard gate → the orchestrator's provider runtime rejects the customer order → customer refunded), keep verify best-effort (`"unverified"` citations on failure), and degrade format failures to `_fallback_report`.

Policy rationale: research is the hard gate — with no findings there is no report, so abort and refund. Verify and format degrade gracefully (a verified-but-plainly-formatted report still has value). `_hire_with_failover` does not record a phantom "no alternate" attempt: if the retry finds no other candidate it keeps the first failure.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_orchestrator_resilience.py
import pytest

from coo_agent.catalog import Catalog
from coo_agent.config import Config
from coo_agent.orchestrator import (
    OrchestratorError, make_orchestrator_precheck, make_orchestrator_work_fn,
)
from coo_agent.planner import Plan, PlanStep
from coo_agent.provider_runtime import ProviderRuntime
from coo_agent.requester import hire
from coo_agent.schemas import (
    Depth, FactCheckDeliverable, FactCheckRequest, Finding, FormatDeliverable,
    FormatRequest, OrchestratorRequest, ResearchDeliverable, ResearchRequest,
    Style, Verdict, VerdictItem,
)
from coo_agent.testing.fake_cap import FakeExchange, FakeCapClient, Fault


def _p_research(d): return ResearchRequest.model_validate(d)
def _p_verify(d): return FactCheckRequest.model_validate(d)
def _p_format(d): return FormatRequest.model_validate(d)


async def _research_work(req: ResearchRequest) -> ResearchDeliverable:
    return ResearchDeliverable(findings=[
        Finding(statement=f"F{i}:{req.query}", source_url=f"https://e/{i}",
                source_title=f"T{i}", snippet="s", confidence=0.9)
        for i in range(req.num_sources)])


async def _verify_work(req: FactCheckRequest) -> FactCheckDeliverable:
    return FactCheckDeliverable(verdicts=[
        VerdictItem(statement=c.statement, verdict=Verdict.supported, confidence=0.8)
        for c in req.claims])


async def _format_work(req: FormatRequest) -> FormatDeliverable:
    return FormatDeliverable(report_markdown=f"# {req.title}\n\nok", references=[])


def _cfg():
    return Config(api_url="", ws_url="", rpc_url=None, anthropic_api_key="",
                  model="m", fee_rate=0.0, margin_floor=0.0,
                  orchestrator_price=0.50, agents={})


class StubPlanner:
    def __init__(self, steps, title="T", fanout=1):
        self._plan = Plan(steps=steps, fanout=fanout, est_cost=0.0, title=title)

    async def plan(self, req, catalog, budget):
        return self._plan


def _fmt_step(title="T", style="report"):
    return PlanStep(role="format",
                    inputs={"title": title, "style": style, "audience": None},
                    critical=True, group=2)


CATALOG_2R = (
    "research:\n"
    "  - { service_id: svc_r1, price_usdc: 0.05, tags: [] }\n"
    "  - { service_id: svc_r2, price_usdc: 0.05, tags: [] }\n"
    "verify:\n  - { service_id: svc_v, price_usdc: 0.05, tags: [] }\n"
    "format:\n  - { service_id: svc_f, price_usdc: 0.05, tags: [] }\n"
)


def _catalog(tmp_path, body):
    p = tmp_path / "catalog.yaml"
    p.write_text(body)
    return Catalog.load(str(p))


async def test_research_fails_over_to_alternate(tmp_path):
    catalog = _catalog(tmp_path, CATALOG_2R)
    ex = FakeExchange(fee_rate=0.0)
    FakeCapClient(ex, "r1", serves=[("svc_r1", 0.05)],
                  fault=Fault(reject_negotiation=True))   # svc_r1 always rejects
    good = FakeCapClient(ex, "r2", serves=[("svc_r2", 0.05)])
    fmtp = FakeCapClient(ex, "f", serves=[("svc_f", 0.05)])
    orch = FakeCapClient(ex, "orchestrator")
    ex.credit("orchestrator", 1.0)
    ProviderRuntime(good, "svc_r2", _p_research, _research_work).install()
    ProviderRuntime(fmtp, "svc_f", _p_format, _format_work).install()

    planner = StubPlanner([
        PlanStep("research", {"query": "X", "num_sources": 2}, True, 0), _fmt_step()])
    work = make_orchestrator_work_fn(orch, catalog, planner, _cfg(), step_timeout=1)
    result = await work(OrchestratorRequest(topic="X", depth=Depth.quick, format=Style.report))

    research = [s for s in result.meta.sub_orders if s.role == "research"]
    assert len(research) == 2
    assert research[0].service_id == "svc_r1" and research[0].status == "rejected"
    assert research[1].service_id == "svc_r2" and research[1].status == "completed"
    assert len(result.citations) == 2


async def test_all_research_failure_raises(tmp_path):
    catalog = _catalog(tmp_path, CATALOG_2R)
    ex = FakeExchange(fee_rate=0.0)
    FakeCapClient(ex, "r1", serves=[("svc_r1", 0.05)], fault=Fault(reject_negotiation=True))
    FakeCapClient(ex, "r2", serves=[("svc_r2", 0.05)], fault=Fault(reject_negotiation=True))
    FakeCapClient(ex, "f", serves=[("svc_f", 0.05)])
    orch = FakeCapClient(ex, "orchestrator")
    ex.credit("orchestrator", 1.0)

    planner = StubPlanner([
        PlanStep("research", {"query": "X", "num_sources": 1}, True, 0), _fmt_step()])
    work = make_orchestrator_work_fn(orch, catalog, planner, _cfg(), step_timeout=1)
    with pytest.raises(OrchestratorError):
        await work(OrchestratorRequest(topic="X", depth=Depth.quick, format=Style.report))


async def test_research_failure_refunds_customer(tmp_path):
    catalog = _catalog(tmp_path, CATALOG_2R)
    ex = FakeExchange(fee_rate=0.0)
    FakeCapClient(ex, "r1", serves=[("svc_r1", 0.05)], fault=Fault(reject_negotiation=True))
    FakeCapClient(ex, "r2", serves=[("svc_r2", 0.05)], fault=Fault(reject_negotiation=True))
    FakeCapClient(ex, "f", serves=[("svc_f", 0.05)])
    orch = FakeCapClient(ex, "orchestrator", serves=[("svc_o", 0.50)])
    customer = FakeCapClient(ex, "customer")
    ex.credit("orchestrator", 1.0)
    ex.credit("customer", 1.0)

    planner = StubPlanner([
        PlanStep("research", {"query": "X", "num_sources": 1}, True, 0), _fmt_step()])
    work = make_orchestrator_work_fn(orch, catalog, planner, _cfg(), step_timeout=1)
    ProviderRuntime(orch, "svc_o",
                    lambda d: OrchestratorRequest.model_validate(d), work).install()

    result = await hire(customer, "svc_o",
                        {"topic": "X", "depth": "standard", "format": "report"},
                        timeout=2)
    assert result.ok is False
    assert result.status == "rejected"
    assert ex.balances["customer"] == pytest.approx(1.0)        # refunded
    assert ex.balances["orchestrator"] == pytest.approx(1.0)    # never paid out


async def test_verify_failure_degrades_to_unverified(tmp_path):
    catalog = _catalog(tmp_path, CATALOG_2R)
    ex = FakeExchange(fee_rate=0.0)
    r = FakeCapClient(ex, "r", serves=[("svc_r1", 0.05)])
    FakeCapClient(ex, "v", serves=[("svc_v", 0.05)], fault=Fault(reject_negotiation=True))
    fmtp = FakeCapClient(ex, "f", serves=[("svc_f", 0.05)])
    orch = FakeCapClient(ex, "orchestrator")
    ex.credit("orchestrator", 1.0)
    ProviderRuntime(r, "svc_r1", _p_research, _research_work).install()
    ProviderRuntime(fmtp, "svc_f", _p_format, _format_work).install()

    planner = StubPlanner([
        PlanStep("research", {"query": "X", "num_sources": 2}, True, 0),
        PlanStep("verify", {"strictness": "normal"}, False, 1),
        _fmt_step()])
    work = make_orchestrator_work_fn(orch, catalog, planner, _cfg(), step_timeout=1)
    result = await work(OrchestratorRequest(topic="X", depth=Depth.standard, format=Style.report))

    verify_orders = [s for s in result.meta.sub_orders if s.role == "verify"]
    assert verify_orders and all(s.status == "rejected" for s in verify_orders)
    assert all(c.verdict == "unverified" for c in result.citations)
    assert result.report_markdown.startswith("# ")


async def test_format_failure_degrades_to_fallback(tmp_path):
    catalog = _catalog(tmp_path, CATALOG_2R)
    ex = FakeExchange(fee_rate=0.0)
    r = FakeCapClient(ex, "r", serves=[("svc_r1", 0.05)])
    FakeCapClient(ex, "f", serves=[("svc_f", 0.05)], fault=Fault(reject_negotiation=True))
    orch = FakeCapClient(ex, "orchestrator")
    ex.credit("orchestrator", 1.0)
    ProviderRuntime(r, "svc_r1", _p_research, _research_work).install()

    planner = StubPlanner([
        PlanStep("research", {"query": "Topic", "num_sources": 2}, True, 0),
        _fmt_step(title="My Title")])
    work = make_orchestrator_work_fn(orch, catalog, planner, _cfg(), step_timeout=1)
    result = await work(OrchestratorRequest(topic="Topic", depth=Depth.quick, format=Style.report))

    fmt_orders = [s for s in result.meta.sub_orders if s.role == "format"]
    assert fmt_orders and all(s.status == "rejected" for s in fmt_orders)
    assert result.report_markdown.startswith("# My Title")   # fallback report
    assert "F0:Topic" in result.report_markdown
    assert len(result.citations) == 2


async def test_precheck_rejects_when_underfunded(tmp_path):
    catalog = _catalog(tmp_path, CATALOG_2R)
    ex = FakeExchange(fee_rate=0.0)
    orch = FakeCapClient(ex, "orchestrator")
    ex.credit("orchestrator", 1.0)
    precheck = make_orchestrator_precheck(orch, _cfg())   # budget == 0.50

    await precheck(None)               # 1.0 >= 0.50, no raise
    ex.balances["orchestrator"] = 0.10
    with pytest.raises(OrchestratorError):
        await precheck(None)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_orchestrator_resilience.py -q`
Expected: FAIL with `ImportError: cannot import name 'OrchestratorError'` (and `make_orchestrator_precheck`).

- [ ] **Step 3: Update `coo_agent/orchestrator.py`**

Add the `get_balance`-based precheck + failover and rewrite `make_orchestrator_work_fn`. The full file:

```python
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
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_orchestrator_resilience.py tests/test_orchestrator.py -q`
Expected: PASS (Task 14's 3 tests still pass + Task 15's 6 tests = 9 passed).

- [ ] **Step 5: Commit**

```bash
git add coo_agent/orchestrator.py tests/test_orchestrator_resilience.py
git commit -m "feat: add orchestrator failover, working-capital precheck, refund-on-fail"
```

---

## Milestone C — Composition roots (entrypoints) + ops glue

> Milestone C wires the pure logic of Milestones A/B to a runtime. All real-SDK
> wiring lives in `examples/` (the composition root); `coo_agent/` stays pure and
> fake-testable. Entrypoints construct clients **inside `main()`** and import the
> real adapter (`coo_agent.real_cap.RealCapClient`, Task 20) **lazily inside a
> helper**, so every example module imports cleanly before the adapter exists.

### Task 16: `examples/` entrypoints + catalog env-substitution helper

**Files:**
- Create: `examples/__init__.py`
- Create: `examples/_bootstrap.py`
- Create: `examples/run_orchestrator.py`
- Create: `examples/run_research.py`
- Create: `examples/run_verify.py`
- Create: `examples/run_format.py`
- Create: `examples/demo_client.py`
- Test: `tests/test_examples.py`

**Interfaces:**
- Consumes: `Config.from_env` (Task 3), `Catalog.load` (Task 4), `LLM` (Task 5),
  `Planner` (Task 6), `make_research_work`/`make_verify_work`/`make_format_work`
  (Tasks 7-9), `ProviderRuntime` (Task 12), `hire` (Task 13),
  `make_orchestrator_work_fn`/`make_orchestrator_precheck` (Tasks 14-15),
  `ResearchRequest`/`FactCheckRequest`/`FormatRequest`/`OrchestratorRequest`
  (Task 2). The `parse_fn` each runtime needs is the pydantic model's
  `.model_validate` bound method.
- Produces:
  - `substitute_env(text:str, env:Mapping[str,str]) -> str` — resolves `${VAR}`
    / `$VAR` placeholders via `string.Template.safe_substitute` (missing vars
    left intact).
  - `load_catalog(path:str, env:Mapping[str,str]|None=None) -> Catalog` — reads
    the catalog file, substitutes env, parses via `Catalog.load` (single parser;
    no duplicated YAML logic).
  - `build_llm(config:Config) -> LLM` — wraps `anthropic.AsyncAnthropic`
    (imported lazily).
  - `build_cap_client(sk_key:str, config:Config) -> CapClient` — constructs
    `RealCapClient(sk_key, api_url, ws_url, rpc_url=None)` (imported lazily;
    **Task 20 MUST match this constructor signature**).
  - Each entrypoint module exposes `async def main()` and an
    `if __name__ == "__main__": asyncio.run(main())` guard.

- [ ] **Step 1: Write the failing tests**

`tests/test_examples.py`:
```python
import importlib

import pytest

from examples._bootstrap import substitute_env, load_catalog

EXAMPLE_MODULES = [
    "examples._bootstrap",
    "examples.run_orchestrator",
    "examples.run_research",
    "examples.run_verify",
    "examples.run_format",
    "examples.demo_client",
]


def test_substitute_env_resolves_brace_and_bare():
    out = substitute_env("a: ${FOO}\nb: $BAR\nc: ${MISSING}", {"FOO": "x", "BAR": "y"})
    assert "a: x" in out and "b: y" in out
    assert "${MISSING}" in out  # safe_substitute leaves unknowns intact


def test_load_catalog_substitutes_service_ids(tmp_path):
    p = tmp_path / "catalog.yaml"
    p.write_text(
        'research:\n  - { service_id: "${RESEARCH_SERVICE_ID}", price_usdc: 0.05 }\n'
        'verify:\n  - { service_id: "v", price_usdc: 0.05 }\n'
        'format:\n  - { service_id: "f", price_usdc: 0.06 }\n',
        encoding="utf-8",
    )
    cat = load_catalog(str(p), {"RESEARCH_SERVICE_ID": "svc_r"})
    assert cat.select("research").service_id == "svc_r"


@pytest.mark.parametrize("mod", EXAMPLE_MODULES)
def test_example_module_imports_without_adapter(mod):
    m = importlib.import_module(mod)
    if mod != "examples._bootstrap":
        assert callable(getattr(m, "main"))
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_examples.py -q`
Expected: FAIL — `ModuleNotFoundError: examples._bootstrap`.

- [ ] **Step 3: Write `examples/__init__.py`**

```python
```

(Empty file — makes `examples/` an importable package so `python -m examples.run_orchestrator` and the import-smoke test work.)

- [ ] **Step 4: Write `examples/_bootstrap.py`**

```python
from __future__ import annotations

import os
import tempfile
from string import Template
from typing import Mapping, Optional

from coo_agent.cap_client import CapClient
from coo_agent.catalog import Catalog
from coo_agent.config import Config
from coo_agent.llm import LLM


def substitute_env(text: str, env: Mapping[str, str]) -> str:
    return Template(text).safe_substitute(env)


def load_catalog(path: str, env: Optional[Mapping[str, str]] = None) -> Catalog:
    env = dict(os.environ if env is None else env)
    with open(path, "r", encoding="utf-8") as fh:
        rendered = substitute_env(fh.read(), env)
    # Render to a temp file so Catalog.load stays the single YAML parser/validator.
    tmp = tempfile.NamedTemporaryFile(
        "w", suffix=".yaml", delete=False, encoding="utf-8")
    try:
        tmp.write(rendered)
        tmp.close()
        return Catalog.load(tmp.name)
    finally:
        os.unlink(tmp.name)


def build_llm(config: Config) -> LLM:
    from anthropic import AsyncAnthropic  # lazy: keep import-smoke independent

    client = AsyncAnthropic(api_key=config.anthropic_api_key)
    return LLM(client, config.model)


def build_cap_client(sk_key: str, config: Config) -> CapClient:
    # Lazy import: the real adapter lands in Task 20. Deferring it here lets every
    # example module import cleanly before the adapter exists.
    from coo_agent.real_cap import RealCapClient

    return RealCapClient(sk_key=sk_key, api_url=config.api_url,
                         ws_url=config.ws_url, rpc_url=config.rpc_url)
```

- [ ] **Step 5: Write `examples/run_research.py`**

```python
from __future__ import annotations

import asyncio

from coo_agent.config import Config
from coo_agent.provider_runtime import ProviderRuntime
from coo_agent.schemas import ResearchRequest
from coo_agent.specialists.research import make_research_work
from examples._bootstrap import build_cap_client, build_llm


async def main() -> None:
    config = Config.from_env()
    creds = config.agents["research"]
    cap = build_cap_client(creds.sk_key, config)
    runtime = ProviderRuntime(
        cap=cap,
        service_id=creds.service_id,
        parse_fn=ResearchRequest.model_validate,
        work_fn=make_research_work(build_llm(config)),
    )
    print(f"[research] provider up on service {creds.service_id}")
    await runtime.run()


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 6: Write `examples/run_verify.py`**

```python
from __future__ import annotations

import asyncio

from coo_agent.config import Config
from coo_agent.provider_runtime import ProviderRuntime
from coo_agent.schemas import FactCheckRequest
from coo_agent.specialists.verify import make_verify_work
from examples._bootstrap import build_cap_client, build_llm


async def main() -> None:
    config = Config.from_env()
    creds = config.agents["verify"]
    cap = build_cap_client(creds.sk_key, config)
    runtime = ProviderRuntime(
        cap=cap,
        service_id=creds.service_id,
        parse_fn=FactCheckRequest.model_validate,
        work_fn=make_verify_work(build_llm(config)),
    )
    print(f"[verify] provider up on service {creds.service_id}")
    await runtime.run()


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 7: Write `examples/run_format.py`**

```python
from __future__ import annotations

import asyncio

from coo_agent.config import Config
from coo_agent.provider_runtime import ProviderRuntime
from coo_agent.schemas import FormatRequest
from coo_agent.specialists.format import make_format_work
from examples._bootstrap import build_cap_client, build_llm


async def main() -> None:
    config = Config.from_env()
    creds = config.agents["format"]
    cap = build_cap_client(creds.sk_key, config)
    runtime = ProviderRuntime(
        cap=cap,
        service_id=creds.service_id,
        parse_fn=FormatRequest.model_validate,
        work_fn=make_format_work(build_llm(config)),
    )
    print(f"[format] provider up on service {creds.service_id}")
    await runtime.run()


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 8: Write `examples/run_orchestrator.py`**

```python
from __future__ import annotations

import asyncio

from coo_agent.config import Config
from coo_agent.orchestrator import (make_orchestrator_precheck,
                                     make_orchestrator_work_fn)
from coo_agent.planner import Planner
from coo_agent.provider_runtime import ProviderRuntime
from coo_agent.schemas import OrchestratorRequest
from examples._bootstrap import build_cap_client, build_llm, load_catalog


async def main() -> None:
    config = Config.from_env()
    creds = config.agents["orchestrator"]
    cap = build_cap_client(creds.sk_key, config)
    catalog = load_catalog("catalog.yaml")
    planner = Planner(build_llm(config))
    runtime = ProviderRuntime(
        cap=cap,
        service_id=creds.service_id,
        parse_fn=OrchestratorRequest.model_validate,
        work_fn=make_orchestrator_work_fn(cap, catalog, planner, config),
        precheck_fn=make_orchestrator_precheck(cap, config),
    )
    print(f"[orchestrator] provider up on service {creds.service_id}")
    await runtime.run()


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 9: Write `examples/demo_client.py`**

```python
from __future__ import annotations

import asyncio
import json
import sys

from coo_agent.config import Config
from coo_agent.requester import hire
from examples._bootstrap import build_cap_client

DEFAULT_TOPIC = "Impact of AI coding agents on freelance software work in 2026"


async def main() -> None:
    config = Config.from_env()
    creds = config.agents["demo_customer"]
    cap = build_cap_client(creds.sk_key, config)
    orchestrator_service_id = config.agents["orchestrator"].service_id
    topic = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_TOPIC
    requirements = {
        "topic": topic,
        "depth": "standard",
        "format": "report",
        "audience": "general",
    }
    await cap.connect()
    try:
        result = await hire(cap, orchestrator_service_id, requirements, timeout=900)
    finally:
        await cap.close()
    print(json.dumps({k: v for k, v in result.__dict__.items()
                      if k != "deliverable"}, indent=2, default=str))
    if result.ok and result.deliverable is not None:
        print("\n" + "=" * 60 + "\n")
        print(result.deliverable["report_markdown"])
    else:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 10: Run to verify it passes**

Run: `pytest tests/test_examples.py -q`
Expected: PASS (8 passed — 2 helper tests + 6 import-smoke params). Imports
succeed even though `coo_agent/real_cap.py` does not exist yet, because the
adapter import is deferred inside `build_cap_client`.

- [ ] **Step 11: Commit**

```bash
git add examples/ tests/test_examples.py
git commit -m "feat: add provider/requester entrypoints + catalog env-substitution"
```

---

### Task 17: Procfile + Makefile + `scripts/check_balances.py`

**Files:**
- Create: `Procfile`
- Create: `Makefile`
- Create: `scripts/__init__.py`
- Create: `scripts/check_balances.py`
- Test: `tests/test_scripts.py`

**Interfaces:**
- Consumes: `Config.from_env` (Task 3), `build_cap_client` (Task 16),
  `CapClient.get_balance`/`connect`/`close` (Task 10).
- Produces: `scripts.check_balances.main` (async) — prints each funded agent's
  AA-wallet balance. `Procfile` runs the 4 provider loops under `honcho`;
  `Makefile` wraps install/agents/demo/test/check/balances.

- [ ] **Step 1: Write the failing test**

`tests/test_scripts.py`:
```python
import importlib


def test_check_balances_importable():
    m = importlib.import_module("scripts.check_balances")
    assert callable(m.main)
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_scripts.py -q`
Expected: FAIL — `ModuleNotFoundError: scripts.check_balances`.

- [ ] **Step 3: Write `scripts/__init__.py`**

```python
```

(Empty — makes `scripts/` an importable package for the smoke test.)

- [ ] **Step 4: Write `scripts/check_balances.py`**

```python
from __future__ import annotations

import asyncio

from coo_agent.config import Config
from examples._bootstrap import build_cap_client


async def main() -> None:
    config = Config.from_env()
    print(f"{'agent':14s} {'service_id':26s} balance")
    for name, creds in config.agents.items():
        if not creds.sk_key:
            continue
        cap = build_cap_client(creds.sk_key, config)
        await cap.connect()
        try:
            balance = await cap.get_balance()
        finally:
            await cap.close()
        print(f"{name:14s} {creds.service_id or '-':26s} {balance:.4f} USDC")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 5: Write `Procfile`**

```Procfile
orchestrator: python -m examples.run_orchestrator
research: python -m examples.run_research
verify: python -m examples.run_verify
format: python -m examples.run_format
```

- [ ] **Step 6: Write `Makefile`**

```makefile
.PHONY: install agents demo test check balances

install:
	pip install -e ".[dev]"

# Run all four provider loops together (orchestrator + 3 specialists).
agents:
	honcho start

# Fire one customer order at the orchestrator (optional: make demo TOPIC="...").
demo:
	python -m examples.demo_client "$(TOPIC)"

test:
	pytest -q

# Full local gate: compile-check then the unit suite (no chain, no network).
check:
	python -m compileall -q coo_agent examples scripts
	pytest -q

balances:
	python -m scripts.check_balances
```

- [ ] **Step 7: Run to verify it passes**

Run: `pytest tests/test_scripts.py -q`
Expected: PASS (1 passed).

- [ ] **Step 8: Commit**

```bash
git add Procfile Makefile scripts tests/test_scripts.py
git commit -m "chore: add Procfile, Makefile, and balance-check script"
```

---

## Milestone D — Live CAP integration (human gates) + ship

> Everything above is provable on a laptop with no network. Milestone D is where
> the agent meets the real chain. Tasks 18-19 are **HUMAN GATES**: a person runs
> them, because they touch real credentials, real USDC, and the live dashboard.
> Do not write the real adapter (Task 20) until Task 18's notes file exists —
> the adapter must be coded against *observed* SDK behavior, not assumptions.

### Task 18: Phase 0 SDK spike (HUMAN GATE — record real SDK interface)

**Goal:** Replace every "verify against repo before relying" assumption with
observed fact, captured in one notes file the adapter (Task 20) is built from.

**Files:**
- Create: `docs/superpowers/notes/cap-sdk-interface.md`

**This task has no automated test.** Its deliverable is the notes file; Task 20
depends on it. Do not proceed to Task 20 until every ❓ below is resolved.

- [ ] **Step 1: Install the SDK in the project venv**

Run: `pip install croo-sdk`
If the package name or version differs from the docs, record the **actual**
`pip install` line that worked. If install fails, capture the error and stop —
this blocks Milestone D.

- [ ] **Step 2: Run the official requester+provider quickstart end-to-end**

Follow `github.com/CROO-Network/go-sdk` (or the Python SDK's `examples/provider`
and `examples/requester`) against a known `CROO_TARGET_SERVICE_ID`. Drive one
order through the full lifecycle: negotiate → accept → pay → deliver → settle.
Confirm it settles on Base mainnet.

- [ ] **Step 3: Record the real interface into `docs/superpowers/notes/cap-sdk-interface.md`**

Fill in every field with **observed** values (not doc guesses). Template:

```markdown
# CAP SDK — observed interface (Phase 0 spike, <date>)

## Install
- working install line: `pip install ...`
- imported as: `import ...`  (e.g. `from croo_sdk import Client`)
- python version used:

## Client construction
- constructor signature + required kwargs (api key, api url, ws url, rpc?):
- how the SK key is passed (`croo_sk_...`):

## Requester methods (map to our CapClient Protocol)
For each, record the REAL name, params, and return shape:
- negotiate_order(...)        -> our negotiate_order
- accept/await order-created  -> our await_order_created   ❓ is "order created" a return value or only a WS event?
- pay_order(...)              -> our pay_order              ❓ does it auto-approve USDC?
- await completion            -> our await_completion       ❓ poll vs WS?
- get_delivery(...)           -> our get_delivery
- get_download_url(...)       -> our get_download_url

## Provider methods
- accept_negotiation(...) / accept_negotiation_with_fund_address(...)  ❓ exact name + fund_address param
- reject_negotiation(...)
- deliver_order(...)          ❓ deliverable arg type: dict? str? + file_url handling
- reject_order(...)
- upload_file(...)            -> our upload_file            ❓ args + return (file_id vs url)

## Both
- get_order / list_orders / list_negotiations
- get_balance(...)            ❓ which address does it read? AA wallet vs controller

## WebSocket events
- connect call:               (our connect / run_forever)
- event names + payload shape for each:
  NEGOTIATION_CREATED / NEGOTIATION_REJECTED / NEGOTIATION_EXPIRED /
  ORDER_CREATED / ORDER_PAID / ORDER_COMPLETED / ORDER_REJECTED / ORDER_EXPIRED
- how requirements/deliverable JSON is carried on each event

## Errors
- exception type(s) the SDK raises:
- how to detect: insufficient balance / invalid status / not found
  (maps to our is_insufficient_balance / is_invalid_status / is_not_found)

## Economics (confirm on-chain / dashboard)
- platform fee rate (the real PLATFORM_FEE_RATE):           ❓
- USDC token address on Base used for settlement:           ❓
- gas: confirmed sponsored (0 gas) during launch window?    ❓

## Service discovery
- ❓ is there ANY list/search-services API? (orchestrator hires from catalog.yaml
  either way, but record the answer so we know if dynamic discovery is possible)
```

- [ ] **Step 4: Reconcile findings back into the code contract**

If observed reality diverges from our `CapClient` Protocol (Task 10) or the
domain dataclasses, note the required adapter mapping **in the notes file**
(do not change Task 10's Protocol — the adapter absorbs the difference). Update
`.env.example` / `pyproject.toml` only if the install name or a required env var
actually differs.

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/notes/cap-sdk-interface.md
git commit -m "docs: record observed CAP SDK interface from Phase 0 spike"
```

---

### Task 19: Dashboard registration + funding (HUMAN GATE)

**Goal:** Bring 5 agents to life on `agent.croo.network`, wire their real
credentials into local config, and fund the wallets so live orders settle.

**Files:**
- Modify: `.env` (local, **never committed** — see [[`.gitignore`]] already ignores it)
- Modify: `catalog.yaml` (only if adding external partner serviceIds)

**This task has no automated test.** Verify success with `make balances`
(Task 17) at the end.

- [ ] **Step 1: Register 5 agents on the dashboard**

On `agent.croo.network`, create 5 agents (each mints an AA wallet + Agent DID
and issues a `croo_sk_...` key):
`orchestrator`, `research`, `verify`, `format`, `demo_customer`.

- [ ] **Step 2: Configure one service per producing agent**

Add a service to each of the 4 producers (the `demo_customer` is buyer-only, no
service). Use the **deliverable schema = the corresponding pydantic model's JSON
schema** from `coo_agent/schemas.py` (Task 2), and the spec's §5 service specs:

| agent | service name | deliverable schema | price (USDC) | SLA |
|---|---|---|---|---|
| orchestrator | Research Report Orchestrator | `OrchestratorDeliverable` | `0.50` | 15 min |
| research | Web Research | `ResearchDeliverable` | `0.05` | 5 min |
| verify | Fact-Check | `FactCheckDeliverable` | `0.05` | 5 min |
| format | Report Formatter | `FormatDeliverable` | `0.06` | 5 min |

The orchestrator's price MUST equal `ORCHESTRATOR_PRICE` in `.env` (default
`0.50`) so `compute_budget` reflects real revenue. Specialist prices MUST match
`catalog.yaml`. If you change any price, change it in **both** places.

- [ ] **Step 3: Copy credentials into `.env`**

From each agent's dashboard page, paste into `.env` (copy from `.env.example`):
- `COO_ORCHESTRATOR_SK`, `RESEARCH_SK`, `VERIFY_SK`, `FORMAT_SK`, `DEMO_CUSTOMER_SK`
- `COO_ORCHESTRATOR_SERVICE_ID`, `RESEARCH_SERVICE_ID`, `VERIFY_SERVICE_ID`, `FORMAT_SERVICE_ID`
- Set `PLATFORM_FEE_RATE` to the value confirmed in Task 18.

**Never commit `.env` or any `croo_sk_` value.** Confirm `git status` does not
list `.env`.

- [ ] **Step 4: Fund the AA wallets with USDC**

Deposit USDC to each agent's **Agent AA Wallet Address** (not the
controller/executor address). Minimum to clear the demo:
- `demo_customer`: ≥ `0.50` (one orchestrator order)
- `orchestrator`: ≥ `0.20` working capital (it pays 3 specialists ≈ `0.16`)
- `research` / `verify` / `format`: small float for any re-hire; they are net
  receivers.
Fund generously enough to run the demo several times.

- [ ] **Step 5: Satisfy the anti-sybil reward-eligibility bar**

The hackathon flags (does not auto-DQ) concentrated self-trade. To stay
reward-eligible, before the deadline:
- Add **≥2 external teams' specialist serviceIds** to `catalog.yaml` under any
  role with `external: true`, so the orchestrator hires **≥3 unique counterparty
  agents** (your 3 specialists + externals exceeds this; externals prove
  cross-team A2A).
- Get **≥5 unique buyer wallets** to order from the orchestrator (other teams'
  agents and/or humans), not just `demo_customer`.
Record partner serviceIds in `catalog.yaml`; re-run `make demo` to confirm
cross-hires settle.

- [ ] **Step 6: Verify funding + wiring**

Run: `make balances`
Expected: every funded agent prints its service id and a non-zero USDC balance.

- [ ] **Step 7: Commit (catalog only — never `.env`)**

```bash
git add catalog.yaml
git commit -m "chore: add external partner serviceIds to catalog"
```

---

### Task 20: `real_cap.py` — `RealCapClient` adapter over `croo-sdk`

**Files:**
- Create: `coo_agent/real_cap.py`
- Test: `tests/test_real_cap.py`

**Interfaces:**
- Consumes: the `CapClient` Protocol + domain types/errors (Task 10); the real
  `croo-sdk` client (constructed lazily; **method names bind to
  `docs/superpowers/notes/cap-sdk-interface.md` from Task 18** — if observed
  names differ, rename only at the call sites in this file and the FakeSDK in the
  test in lock-step).
- Produces: `RealCapClient(sk_key:str, api_url:str, ws_url:str, rpc_url:str|None=None, *, sdk=None)`
  satisfying `CapClient`. The `sdk=` kwarg injects a fake for tests; in prod it is
  `None` and the real client is built on `connect()`. Requester await methods are
  race-safe via a buffered event router (mirrors `FakeCapClient`): an event that
  arrives before its `await_*` is stored "ready"; one that arrives after resolves
  a registered future. Any non-`CapError` SDK exception is normalized to
  `CapError` (preserving `.code` when present); timeouts raise `CapError(code="timeout")`.
  Provider handlers registered via `on(...)` are scheduled as background tasks (not
  awaited inline) so the orchestrator's paid-handler — which itself awaits sub-order
  events on this same router — cannot deadlock a sequential SDK WS pump.

- [ ] **Step 1: Write the failing tests**

`tests/test_real_cap.py`:
```python
import asyncio

import pytest

from coo_agent.cap_client import (CapError, CapEvent, OrderStatus,
                                   is_insufficient_balance, is_invalid_status)
from coo_agent.real_cap import RealCapClient


class _SDKErr(Exception):
    def __init__(self, msg, code):
        super().__init__(msg)
        self.code = code


class FakeSDK:
    """Stand-in for the croo-sdk client; records calls, lets tests inject errors."""

    def __init__(self):
        self.calls = []
        self.balance = 1.0
        self.raise_on = {}  # method name -> exception to raise

    def _maybe_raise(self, name):
        if name in self.raise_on:
            raise self.raise_on[name]

    async def connect_websocket(self, handler):
        self.handler = handler

    async def close(self):
        self.calls.append(("close",))

    async def run_forever(self):
        return None

    async def negotiate_order(self, service_id, requirements):
        self._maybe_raise("negotiate_order")
        return {"negotiation_id": "neg1", "service_id": service_id,
                "requester_did": "did", "requirements": requirements}

    async def pay_order(self, order_id):
        self._maybe_raise("pay_order")
        self.calls.append(("pay", order_id))

    async def accept_negotiation(self, negotiation_id, fund_address=None):
        self._maybe_raise("accept_negotiation")
        self.calls.append(("accept", negotiation_id, fund_address))
        return {"order_id": "o1", "service_id": "svc", "status": "created",
                "price_usdc": 0.05, "requirements": {}, "negotiation_id": negotiation_id}

    async def reject_negotiation(self, negotiation_id, reason=""):
        self.calls.append(("rej_neg", negotiation_id, reason))

    async def deliver_order(self, order_id, deliverable, file_url=None):
        self.calls.append(("deliver", order_id, deliverable, file_url))

    async def reject_order(self, order_id, reason=""):
        self.calls.append(("rej_order", order_id, reason))

    async def upload_file(self, content, filename):
        return "https://files/x"

    async def get_delivery(self, order_id):
        return {"order_id": order_id, "deliverable": {"a": 1}, "file_url": None}

    async def get_download_url(self, file_id):
        return "https://dl/" + file_id

    async def get_order(self, order_id):
        return {"order_id": order_id, "service_id": "svc", "status": "completed",
                "price_usdc": 0.05, "requirements": {}}

    async def list_orders(self):
        return []

    async def list_negotiations(self):
        return []

    async def get_balance(self, address=None):
        return self.balance


async def _connected(fake=None):
    fake = fake or FakeSDK()
    cap = RealCapClient("croo_sk_x", "api", "ws", sdk=fake)
    await cap.connect()
    return cap, fake


async def test_negotiate_and_accept_translate():
    cap, fake = await _connected()
    neg = await cap.negotiate_order("svc", {"topic": "t"})
    assert neg.negotiation_id == "neg1" and neg.service_id == "svc"
    order = await cap.accept_negotiation("neg1", fund_address="0xAA")
    assert order.order_id == "o1" and order.status is OrderStatus.created
    assert ("accept", "neg1", "0xAA") in fake.calls


async def test_await_order_created_from_buffered_event():
    cap, _ = await _connected()
    await cap._dispatch("ORDER_CREATED", {
        "order_id": "o1", "service_id": "svc", "status": "created",
        "price_usdc": 0.05, "requirements": {}, "negotiation_id": "neg1"})
    order = await cap.await_order_created("neg1", timeout=1)
    assert order.order_id == "o1"


async def test_await_completion_resolves_on_later_event():
    cap, _ = await _connected()
    task = asyncio.create_task(cap.await_completion("o1", timeout=1))
    await asyncio.sleep(0)  # let the awaiter register its future first
    await cap._dispatch("ORDER_COMPLETED", {
        "order_id": "o1", "service_id": "svc", "status": "completed",
        "price_usdc": 0.05, "requirements": {}})
    order = await task
    assert order.status is OrderStatus.completed


async def test_await_order_created_times_out():
    cap, _ = await _connected()
    with pytest.raises(CapError) as ei:
        await cap.await_order_created("missing", timeout=0.05)
    assert ei.value.code == "timeout"


async def test_provider_handler_invoked_on_negotiation_event():
    cap, _ = await _connected()
    seen = []

    async def handler(neg):
        seen.append(neg)

    cap.on(CapEvent.NEGOTIATION_CREATED, handler)
    await cap._dispatch("NEGOTIATION_CREATED", {
        "negotiation_id": "n1", "service_id": "svc",
        "requester_did": "did", "requirements": {"q": 1}})
    await asyncio.sleep(0)  # handlers run as background tasks; let it execute
    assert seen and seen[0].negotiation_id == "n1" and seen[0].requirements == {"q": 1}


async def test_sdk_error_normalized_to_cap_error():
    fake = FakeSDK()
    fake.raise_on["accept_negotiation"] = _SDKErr("bad status", "invalid_status")
    cap, _ = await _connected(fake)
    with pytest.raises(CapError) as ei:
        await cap.accept_negotiation("n1")
    assert is_invalid_status(ei.value)


async def test_cap_error_passes_through_unchanged():
    fake = FakeSDK()
    fake.raise_on["pay_order"] = CapError("no funds", code="insufficient_balance")
    cap, _ = await _connected(fake)
    with pytest.raises(CapError) as ei:
        await cap.pay_order("o1")
    assert is_insufficient_balance(ei.value)


async def test_deliver_balance_and_upload_passthrough():
    fake = FakeSDK()
    fake.balance = 2.5
    cap, _ = await _connected(fake)
    await cap.deliver_order("o1", {"report_markdown": "# r"}, file_url="u")
    assert ("deliver", "o1", {"report_markdown": "# r"}, "u") in fake.calls
    assert await cap.get_balance() == 2.5
    assert await cap.upload_file(b"x", "f.json") == "https://files/x"
    delivery = await cap.get_delivery("o1")
    assert delivery.deliverable == {"a": 1}
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_real_cap.py -q`
Expected: FAIL — `ModuleNotFoundError: coo_agent.real_cap`.

- [ ] **Step 3: Write `coo_agent/real_cap.py`**

```python
from __future__ import annotations

import asyncio
from typing import Awaitable, Callable, Optional

from .cap_client import (CapError, CapEvent, Delivery, Negotiation, Order,
                         OrderStatus)

Handler = Callable[[object], Awaitable[None]]

_TERMINAL = (CapEvent.ORDER_COMPLETED, CapEvent.ORDER_REJECTED,
             CapEvent.ORDER_EXPIRED)


def _g(obj, *names, default=None):
    """Read the first present field from a dict OR an object (SDK shape varies)."""
    for n in names:
        if isinstance(obj, dict):
            if n in obj:
                return obj[n]
        elif hasattr(obj, n):
            return getattr(obj, n)
    return default


def _status(raw) -> OrderStatus:
    try:
        return OrderStatus(str(raw).lower())
    except ValueError:
        return OrderStatus.created


class RealCapClient:
    def __init__(self, sk_key: str, api_url: str, ws_url: str,
                 rpc_url: Optional[str] = None, *, sdk=None):
        self._sk = sk_key
        self._api_url = api_url
        self._ws_url = ws_url
        self._rpc_url = rpc_url
        self._sdk = sdk
        self._handlers: dict[CapEvent, list[Handler]] = {}
        self._created_ready: dict[str, Order] = {}
        self._created_waiters: dict[str, asyncio.Future] = {}
        self._done_ready: dict[str, Order] = {}
        self._done_waiters: dict[str, asyncio.Future] = {}
        self._tasks: set = set()  # keep handler tasks alive until they finish

    # --- translation (single reconciliation point vs Task 18 notes) -------
    def _neg_from(self, p) -> Negotiation:
        return Negotiation(
            negotiation_id=_g(p, "negotiation_id", "negotiationId", "id"),
            service_id=_g(p, "service_id", "serviceId", default=""),
            requester_did=_g(p, "requester_did", "requesterDid", default=""),
            requirements=_g(p, "requirements", default={}) or {})

    def _order_from(self, p) -> Order:
        return Order(
            order_id=_g(p, "order_id", "orderId", "id"),
            service_id=_g(p, "service_id", "serviceId", default=""),
            status=_status(_g(p, "status", default="created")),
            price_usdc=float(_g(p, "price_usdc", "priceUsdc", "price", default=0.0) or 0.0),
            requirements=_g(p, "requirements", default={}) or {},
            negotiation_id=_g(p, "negotiation_id", "negotiationId"))

    # --- lifecycle --------------------------------------------------------
    def _build_sdk(self):
        from croo_sdk import Client  # name/params per Task 18 notes

        return Client(api_key=self._sk, api_url=self._api_url,
                      ws_url=self._ws_url, rpc_url=self._rpc_url)

    async def connect(self) -> None:
        if self._sdk is None:
            self._sdk = self._build_sdk()
        await self._sdk.connect_websocket(self._dispatch)

    async def close(self) -> None:
        if self._sdk is not None:
            await self._sdk.close()

    async def run_forever(self) -> None:
        await self._sdk.run_forever()

    def on(self, event: CapEvent, handler: Handler) -> None:
        self._handlers.setdefault(event, []).append(handler)

    # --- event router -----------------------------------------------------
    async def _dispatch(self, event, payload) -> None:
        try:
            ev = event if isinstance(event, CapEvent) else CapEvent(str(event))
        except ValueError:
            return
        # Resolve requester-side futures SYNCHRONOUSLY, before any await, so a
        # blocked handler can never starve a waiter of its event.
        if ev is CapEvent.ORDER_CREATED:
            order = self._order_from(payload)
            key = order.negotiation_id or order.order_id
            self._resolve(self._created_waiters, self._created_ready, key, order)
        elif ev in _TERMINAL:
            order = self._order_from(payload)
            self._resolve(self._done_waiters, self._done_ready, order.order_id, order)
        # Fan out to provider handlers as background tasks rather than awaiting
        # inline. The orchestrator's ORDER_PAID handler itself awaits sub-order
        # events on this same router; if we awaited it here, a sequential SDK
        # WS pump would block on it forever (the sub-order events it waits for
        # can't be read until _dispatch returns). Tasking decouples the pump.
        domain = (self._neg_from(payload) if "NEGOTIATION" in ev.value
                  else self._order_from(payload))
        for handler in list(self._handlers.get(ev, [])):
            task = asyncio.create_task(handler(domain))
            self._tasks.add(task)
            task.add_done_callback(self._on_handler_done)

    def _on_handler_done(self, task: asyncio.Task) -> None:
        self._tasks.discard(task)
        if not task.cancelled() and task.exception() is not None:
            # A provider handler raised. Don't crash the router; surface it.
            print(f"[real_cap] handler task failed: {task.exception()!r}")

    @staticmethod
    def _resolve(waiters, ready, key, value) -> None:
        fut = waiters.pop(key, None)
        if fut is not None and not fut.done():
            fut.set_result(value)
        else:
            ready[key] = value

    async def _await(self, waiters, ready, key, timeout) -> Order:
        if key in ready:
            return ready.pop(key)
        fut = asyncio.get_running_loop().create_future()
        waiters[key] = fut
        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        except asyncio.TimeoutError as exc:
            waiters.pop(key, None)
            raise CapError(f"timed out waiting for {key}", code="timeout") from exc

    # --- error boundary ---------------------------------------------------
    async def _guard(self, coro):
        try:
            return await coro
        except CapError:
            raise
        except Exception as exc:  # adapter boundary: normalize SDK failures
            raise CapError(str(exc), code=getattr(exc, "code", None)) from exc

    # --- requester --------------------------------------------------------
    async def negotiate_order(self, service_id, requirements) -> Negotiation:
        return self._neg_from(
            await self._guard(self._sdk.negotiate_order(service_id, requirements)))

    async def await_order_created(self, negotiation_id, timeout) -> Order:
        return await self._await(self._created_waiters, self._created_ready,
                                 negotiation_id, timeout)

    async def pay_order(self, order_id) -> None:
        await self._guard(self._sdk.pay_order(order_id))

    async def await_completion(self, order_id, timeout) -> Order:
        return await self._await(self._done_waiters, self._done_ready,
                                 order_id, timeout)

    async def get_delivery(self, order_id) -> Delivery:
        raw = await self._guard(self._sdk.get_delivery(order_id))
        return Delivery(order_id=order_id,
                        deliverable=_g(raw, "deliverable", default={}) or {},
                        file_url=_g(raw, "file_url", "fileUrl"))

    async def get_download_url(self, file_id) -> str:
        return await self._guard(self._sdk.get_download_url(file_id))

    # --- provider ---------------------------------------------------------
    async def get_negotiation(self, negotiation_id) -> Negotiation:
        return self._neg_from(
            await self._guard(self._sdk.get_negotiation(negotiation_id)))

    async def accept_negotiation(self, negotiation_id, fund_address=None) -> Order:
        return self._order_from(await self._guard(
            self._sdk.accept_negotiation(negotiation_id, fund_address=fund_address)))

    async def reject_negotiation(self, negotiation_id, reason="") -> None:
        await self._guard(self._sdk.reject_negotiation(negotiation_id, reason=reason))

    async def deliver_order(self, order_id, deliverable, file_url=None) -> None:
        await self._guard(
            self._sdk.deliver_order(order_id, deliverable, file_url=file_url))

    async def reject_order(self, order_id, reason="") -> None:
        await self._guard(self._sdk.reject_order(order_id, reason=reason))

    async def upload_file(self, content, filename) -> str:
        return await self._guard(self._sdk.upload_file(content, filename))

    # --- both -------------------------------------------------------------
    async def get_order(self, order_id) -> Order:
        return self._order_from(await self._guard(self._sdk.get_order(order_id)))

    async def list_orders(self) -> list:
        return [self._order_from(o)
                for o in await self._guard(self._sdk.list_orders())]

    async def list_negotiations(self) -> list:
        return [self._neg_from(n)
                for n in await self._guard(self._sdk.list_negotiations())]

    async def get_balance(self, address=None) -> float:
        return float(await self._guard(self._sdk.get_balance(address=address)))
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_real_cap.py -q`
Expected: PASS (8 passed).

- [ ] **Step 5: Commit**

```bash
git add coo_agent/real_cap.py tests/test_real_cap.py
git commit -m "feat: add RealCapClient adapter over croo-sdk"
```

---

### Task 21: Live CAP smoke test (env-gated)

**Files:**
- Create: `tests/test_live_cap.py`

**Interfaces:**
- Consumes: `Config.from_env`, `build_cap_client` (Task 16), `hire` (Task 13),
  a funded `.env` (Task 19), and the four provider loops running (`make agents`).
- Produces: one real on-chain order driven end-to-end; skipped unless
  `RUN_LIVE_CAP=1` so the default suite stays offline/deterministic.

- [ ] **Step 1: Write the env-gated test**

`tests/test_live_cap.py`:
```python
import os

import pytest

RUN_LIVE = os.getenv("RUN_LIVE_CAP") == "1"
pytestmark = pytest.mark.skipif(
    not RUN_LIVE,
    reason="live CAP test; set RUN_LIVE_CAP=1 with a funded .env and `make agents` running")


async def test_live_orchestrator_order_completes():
    from coo_agent.config import Config
    from coo_agent.requester import hire
    from examples._bootstrap import build_cap_client

    config = Config.from_env()
    creds = config.agents["demo_customer"]
    cap = build_cap_client(creds.sk_key, config)
    orchestrator_service_id = config.agents["orchestrator"].service_id

    await cap.connect()
    try:
        result = await hire(
            cap, orchestrator_service_id,
            {"topic": "test: latest stable Python release",
             "depth": "quick", "format": "brief", "audience": "general"},
            timeout=900)
    finally:
        await cap.close()

    assert result.ok, f"order did not complete: {result.status} ({result.error})"
    assert result.deliverable is not None
    assert result.deliverable["report_markdown"].strip()
    assert result.order_id and result.price_usdc > 0
```

- [ ] **Step 2: Run with the gate OFF (default)**

Run: `pytest tests/test_live_cap.py -q`
Expected: 1 skipped.

- [ ] **Step 3: Run with the gate ON (manual, after `make agents`)**

In one terminal: `make agents`. In another, with a funded `.env`:
Run: `RUN_LIVE_CAP=1 pytest tests/test_live_cap.py -q`
Expected: PASS — a real order settles; `make balances` shows the customer
debited and the orchestrator/specialists credited.

- [ ] **Step 4: Commit**

```bash
git add tests/test_live_cap.py
git commit -m "test: add env-gated live CAP end-to-end smoke test"
```

---

## Milestone E — Ship: README, demo, BUIDL filing

### Task 22: `README.md` + two-tier onboarding

**Files:**
- Create: `README.md`

**Interfaces:**
- Consumes: everything above (the runnable system).
- Produces: a graded README with a try-it (Tier 1: hire the listed agent) and a
  run-it-yourself (Tier 2: stand up the whole stack) path. `<ANGLE>` markers are
  the only fill-ins; replace them once Tasks 19/23 produce real values.

- [ ] **Step 1: Write `README.md`**

````markdown
# COO — Research Report Orchestrator Agent

A callable, paid AI agent on [CROO](https://croo.network) that turns a research
goal into a **cited markdown report** by hiring and paying specialist agents
on-chain (USDC on Base). It is both a **provider** (you hire it) and a
**requester** (it sub-contracts Research, Fact-Check, and Formatting agents over
the CROO Agent Protocol — CAP).

- **Agent Store listing:** <AGENT_STORE_URL>
- **Demo video (≤5 min):** <DEMO_VIDEO_URL>
- **License:** MIT

## How it works

```
customer ──order──▶  COO Orchestrator (provider)
                         │  decompose goal → plan
                         │
        (requester) ─────┼─ hire Research ×N   (parallel, hard gate)
                         ├─ hire Fact-Check     (best-effort)
                         └─ hire Formatter      (degrades to fallback)
                         │
                    assemble cited report ──deliver──▶ customer
```

Every hire is a real CAP order: negotiate → pay (USDC escrowed in CAPVault) →
deliver (hash on-chain) → settle. If all research fails, the orchestrator rejects
the customer's order so the customer is **refunded** — it never bills for an
empty report.

## Service interface

**Input** (order requirements):

| field | type | notes |
|---|---|---|
| `topic` | string | the research goal |
| `depth` | `quick` \| `standard` \| `deep` | controls fan-out + whether fact-check runs |
| `format` | `brief` \| `report` \| `bullet` | output style |
| `audience` | string (optional) | who the report is for |

**Output** (`OrchestratorDeliverable`): `report_markdown`, `citations[]`
(claim + source + verdict), and `meta` (sub-orders, total USDC cost, model).

## Tier 1 — Hire it (no setup)

The orchestrator is listed on the CROO Agent Store. From any CAP requester
(your own agent, or the dashboard), order service `<COO_ORCHESTRATOR_SERVICE_ID>`
with the input above and ~`0.50` USDC. You receive the cited report as the
deliverable. That's the whole product: one call, one settlement.

## Tier 2 — Run it yourself

Requires Python 3.10+ and (for live orders) a funded CROO account.

```bash
git clone git@github.com:StarryDeserts/capstone.git
cd capstone
make install                 # pip install -e ".[dev]"
make test                    # full offline suite — no network, no chain

cp .env.example .env         # then fill in keys/serviceIds (see below)
make agents                  # runs orchestrator + 3 specialists (honcho)
make demo TOPIC="Your research question"   # fires one customer order
make balances                # shows each agent's USDC balance
```

To go live you must register 5 agents on
[agent.croo.network](https://agent.croo.network) (orchestrator, research,
verify, format, demo_customer), add each service with the schema above, paste
the `croo_sk_...` keys and serviceIds into `.env`, and fund each agent's **Agent
AA Wallet** with USDC. See `.env.example` for every variable. The offline test
suite (`make test`) needs none of this.

## Architecture

Pure logic (`coo_agent/`) depends only on our own `CapClient` Protocol and is
fully tested against an in-memory fake (`coo_agent/testing/fake_cap.py`) — no
chain, no SDK. The live `croo-sdk` is isolated behind one adapter
(`coo_agent/real_cap.py`) wired in `examples/`. Swap fake for real without
touching orchestration logic.

```
coo_agent/
  schemas.py        pydantic request/deliverable models
  config.py         env + per-agent creds + budget math
  catalog.py        hireable-specialist catalog + selection
  planner.py        goal → plan (hybrid skeleton + LLM sub-queries)
  llm.py            Claude wrapper (JSON out + web search)
  specialists/      research / verify / format work_fns
  cap_client.py     CapClient Protocol + domain types
  testing/fake_cap.py   in-memory CAP exchange for tests
  provider_runtime.py   generic provider event loop
  requester.py      generic hire() helper
  orchestrator.py   the COO work_fn (plan → hire → assemble)
  real_cap.py       croo-sdk adapter
examples/           runnable entrypoints (composition root)
```

## Security

Never commit `.env` or any `croo_sk_...` key (`.gitignore` already excludes
`.env`). Keys live only in your local environment.
````

- [ ] **Step 2: Verify it renders**

Run: `python -c "import pathlib; print(pathlib.Path('README.md').read_text()[:80])"`
Expected: prints the title line. (Spot-check tables/code-fences render on GitHub.)

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: add README with two-tier onboarding"
```

---

### Task 23: Demo video (≤5 min) + BUIDL filing (HUMAN GATE)

**Goal:** Record the ≤5-minute demo and file the BUIDL on DoraHacks before the
**2026-07-12 17:00** deadline.

**Files:**
- Create: `docs/superpowers/notes/demo-script.md`

**This task has no automated test.** It produces the demo script + a filed BUIDL.

- [ ] **Step 1: Write `docs/superpowers/notes/demo-script.md`**

```markdown
# COO Orchestrator — ≤5-minute demo script

Pre-roll (off camera): funded `.env`, `make agents` already running in a hidden
terminal, `make balances` output captured "before".

| time | on screen | say |
|---|---|---|
| 0:00–0:30 | Agent Store listing page | "This is COO, a paid research-report agent on CROO. You hire it; it hires three other agents to do the work and pays them on-chain." |
| 0:30–1:00 | `catalog.yaml` + architecture diagram | "It's a provider AND a requester: Research, Fact-Check, Formatter — including partner teams' agents — over CAP." |
| 1:00–1:30 | `make balances` (before) | "Here are the wallets before the order." |
| 1:30–3:00 | `make demo TOPIC="..."` running | "One order. Watch it plan, hire research in parallel, fact-check, then format." (show the live order/settlement events) |
| 3:00–4:00 | the printed cited report | "Cited markdown report — every claim has a source and a verdict." |
| 4:00–4:40 | `make balances` (after) + a block explorer | "Customer debited, three specialists credited — real USDC settlement on Base." |
| 4:40–5:00 | repo README | "MIT-licensed, run it yourself in two commands. Links below." |

Keep it under 5:00. Show one real settlement on-chain — no mock-ups (faked demos
are an auto-DQ).
```

- [ ] **Step 2: Record the demo**

Drive a real order with the live stack (Task 19 funded, `make agents` running,
`make demo`). Capture the terminal, the cited report, before/after `make
balances`, and one settlement tx on a Base explorer. Trim to ≤5:00. Upload and
put the URL in `README.md` (`<DEMO_VIDEO_URL>`) and the BUIDL.

- [ ] **Step 3: Pre-submission checklist (each is a hard DQ if missed)**

- [ ] Repo is **public** on GitHub, MIT `LICENSE` present.
- [ ] CAP integration **works live** (Task 21 passed with `RUN_LIVE_CAP=1`).
- [ ] Demo video is **real** (on-chain settlement shown), ≤5 min.
- [ ] README has Agent Store link + demo link + run-it-yourself steps.
- [ ] No `.env` / `croo_sk_` secrets committed (`git log -p | grep -i croo_sk` is empty).
- [ ] Reward-eligibility (reviewed, not auto-DQ): **≥3 unique counterparty
      agents** hired and **≥5 unique buyer wallets** ordered from the
      orchestrator (Task 19 Step 5). Capture proof (order ids / wallets).

- [ ] **Step 4: File the BUIDL on DoraHacks**

Submit to the CROO Agent Hackathon: link the public repo, the demo video, the
Agent Store listing. Pick **≤2 tracks** (recommended: *Research & Intelligence*
+ *Open/Any A2A* — the orchestrator's cross-team hiring is the A2A story). Submit
before **2026-07-12 17:00**.

- [ ] **Step 5: Commit the demo script**

```bash
git add docs/superpowers/notes/demo-script.md
git commit -m "docs: add demo script and submission checklist"
```

---

## Plan complete

Milestones A–C (Tasks 1–17) are fully offline and TDD-driven: `make test` /
`make check` go green with no network, no chain, no secrets. Milestone D
(Tasks 18–21) is the live-CAP integration behind two human gates. Milestone E
(Tasks 22–23) ships the README, demo, and BUIDL filing. The critical
build order: **Tasks 1–17 → Task 18 (SDK spike) → Task 19 (register/fund) →
Tasks 20–21 (adapter + live smoke) → Tasks 22–23 (ship).**

---
