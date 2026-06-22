# COO Orchestrator Agent — Design Spec

- **Date:** 2026-06-22
- **Status:** Approved (pending final spec review)
- **Hackathon deadline:** 2026-07-12 17:00
- **Project:** A paid, callable AI agent for the CROO Agent Hackathon, built on CAP (CROO Agent Protocol).

---

## 1. Summary

The **COO Orchestrator Agent** is a CROO-listed service that turns a high-level research request into a cited report by **hiring and paying a team of specialist agents on-chain**. A customer (human or agent) pays the orchestrator in USDC; the orchestrator then acts as a buyer itself, sub-contracting Research, Fact-Check, and Format specialist agents over CAP, and assembles their deliverables into a final cited report.

This directly showcases the hackathon's thesis — **A2A composability + on-chain commerce** — because a single customer call fans out into ≥4 real on-chain CAP orders across ≥3 distinct counterparty agents.

**Tracks:** Research & Intelligence (primary) + Data & Verification (secondary).

---

## 2. Context & Constraints

### Hackathon submission requirements (all five must hold)
1. Listed on CROO Agent Store (discoverable by humans and agents).
2. Integrated with CAP (callable, settles on-chain).
3. Open source — public GitHub repo, MIT license.
4. ≤5-min demo video + README (setup, SDK methods used, integration notes).
5. BUIDL filed on DoraHacks before **2026-07-12 17:00**.

### Anti-sybil rules (reviewed; not auto-DQ but reward-impacting)
- Flags: `<3` unique counterparty agents, `<5` unique buyer wallets, concentrated self-trade.
- Hard DQ: private repo, copy-paste fork, fake demo, broken CAP integration, failed human spot-check.
- **Design implication:** must produce real external counterparties/buyers, not just loop our own agents. The architecture builds in hooks for this (catalog external slot, listed/callable orchestrator).

### Verified platform facts
- **Chain:** Base Mainnet (chainId 8453); settlement in **USDC**.
- **Gas:** sponsored by CROO (ERC-4337 account abstraction); 0% gas during the launch window.
- **Contracts:** CAPCore `0xaD46f1Eba2fe9cBB689D2874a52039192F2ac821` (state), CAPVault `0x33ECdcC8dD32330ec5a62AB1986F25ED5B5D170d` (escrow/funds), CROOValidationModule `0xfCc7eefd6D22bC6a4F35B467928ecAF738d0B3b8`.
- **Registration is manual in the dashboard** (agent.croo.network): creates an AA wallet + Agent DID, issues an API key `croo_sk_...`. The SDK is runtime-only.
- **No programmatic service-discovery API.** Discovery is off-chain/user-facing via the "Navigator" + skill tags; a requester hires by targeting a known `serviceId`. → The orchestrator hires from a **configured catalog** of serviceIds.
- **SDKs:** Go / Node.js / Python (`pip install croo-sdk`, async). Env: `CROO_API_URL`, `CROO_WS_URL`, `CROO_SDK_KEY`, optional `BASE_RPC_URL`.

---

## 3. Key Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Vertical | Research-report production | Naturally needs 3 distinct specialists → ≥3 counterparties by construction; spans 2 allowed tracks; cleanest demo. |
| Specialist sourcing | Build all 3 in-house **+ external plug-in slot** in catalog | Demo reliability + control, while enabling real external counterparties/buyers for anti-sybil. |
| AI stack | Anthropic Claude (+ web search for citations) | Highest planning/writing quality; claude-api skill patterns (caching, tool use). |
| Orchestration engine | **Hybrid skeleton** | Default Research→Verify→Format skeleton; Claude decides skip/repeat/parallel-fanout per goal and crafts each sub-task input + merge. Reliability of a fixed pipeline + most of the intelligence of a dynamic DAG, bounded for demo safety. |
| Language | Python | Best AI ecosystem fit; croo-sdk is async. |

---

## 4. Architecture

### Agents (each a separate CROO agent: own DID + AA wallet + `croo_sk_` key)

| Agent | CROO role | Responsibility |
|---|---|---|
| **COO Orchestrator** (submission) | Provider → flips to Requester when hired | Accept goal → plan → hire specialists → assemble cited report |
| **Research specialist** | Provider | sub-question → Claude + web search → findings with sources (url/snippet/confidence) |
| **Fact-Check specialist** | Provider | claims + sources → per-claim verdict (supported/contradicted/unverifiable) + evidence |
| **Format specialist** | Provider | verified findings → polished cited report |
| **Demo customer** (test only) | Requester | hires the orchestrator in the scripted demo |

### On-chain duality (the core idea)

```
Customer (human/agent) --pay USDC--> [COO Orchestrator] --pay USDC--> Research specialist
                                       (Provider role)   --pay USDC--> Fact-Check specialist
                                       (internally Requester)--pay USDC--> Format specialist

Each arrow = one CAP order (negotiate -> pay -> deliver -> settle).
One customer call = >=4 on-chain orders = >=3 distinct counterparty agents.
```

### Python modules (single-responsibility, independently testable)

- `config.py` — env + per-agent keys, budgets, caps.
- `schemas.py` — pydantic requirement/deliverable models for all 4 services.
- `llm.py` — Claude wrapper (prompt caching, web-search tool use).
- `cap_client.py` — thin wrapper over croo-sdk; unifies Provider and Requester operations + error helpers.
- `provider_runtime.py` — generic provider loop: connect WS, validate requirements, accept, run an injected `work_fn` on payment, deliver. **All 4 agents reuse it** with different `work_fn`s.
- `requester.py` — generic "hire" helper: negotiate → pay → await completion → fetch delivery.
- `catalog.py` — load/validate catalog (role → list of serviceIds + price + schema + tags); selection policy (cheapest / round-robin to spread counterparties); includes an `external` section.
- `planner.py` — hybrid-skeleton engine: goal + catalog + budget → bounded `Plan` (steps, capped fan-out, per-step inputs, merge instructions).
- `orchestrator.py` — orchestrator `work_fn`: plan → hire specialists (parallel/sequential per plan) → collect → assemble → handle partial failure + budget.
- `specialists/{research,verify,format}.py` — each a `work_fn`.

---

## 5. Data Flow & Schemas

### Service schemas (structured JSON deliverables for machine consumption)

```
# COO Orchestrator
Req:  { topic: str, depth: quick|standard|deep, format: brief|report|bullet,
        max_sources?: int, audience?: str }
Deliv:{ report_markdown: str,
        citations: [{ claim, source_url, snippet, confidence, verdict }],
        meta: { sub_orders:[{role, service_id, order_id, price_usdc, status}],
                total_cost_usdc, model } }

# Research specialist
Req:  { query: str, num_sources: int, recency?: str, focus?: str }
Deliv:{ findings: [{ statement, source_url, source_title, snippet, confidence, published_at? }] }

# Fact-Check specialist
Req:  { claims: [{ statement, source_url? }], strictness: low|normal|high }
Deliv:{ verdicts: [{ statement, verdict: supported|contradicted|unverifiable,
                     evidence_url, evidence_snippet, confidence, notes }] }

# Format specialist
Req:  { title: str, verified_findings: [...], style: brief|report|bullet, audience?: str }
Deliv:{ report_markdown: str, references: [{ n, url, title }] }
```

### End-to-end sequence (real CAP methods + WebSocket events)

```
1. Customer (Requester) negotiate_order(orchestrator_service_id, {topic,...})
2. Orchestrator receives NEGOTIATION_CREATED -> validate requirements schema
   -> accept_negotiation (backend dual-sig submits on-chain createOrder) -> both: ORDER_CREATED
3. Customer pay_order -> USDC escrowed in CAPVault -> Orchestrator: ORDER_PAID
   -> orchestrator SLA countdown starts, work_fn begins
4. Orchestrator: plan = planner.plan(goal, catalog, budget)
   e.g. [research x N (parallel), verify (after research), format (after verify)]
5. Per step, Orchestrator as Requester hires a specialist:
   negotiate_order -> specialist accept_negotiation -> pay_order (from AA working capital)
   -> specialist work -> deliver_order -> Orchestrator ORDER_COMPLETED + get_delivery
   - research steps run via asyncio.gather (capped at N)
   - verify consumes research findings; format consumes verified findings
6. Orchestrator merges -> (large files via upload_file) -> deliver_order(customer_order, final)
7. Customer ORDER_COMPLETED -> get_delivery -> report.
   CAPVault settles orchestrator order (fee -> Treasury, remainder -> orchestrator AA wallet,
   reimbursing working capital + margin).
```

---

## 6. Payments, Escrow, Working Capital, Pricing

- **Fee model:** platform fee rate `f` (exact value TBD — verify) goes to Treasury; the requester pays full price, the provider receives `price x (1 - f)`.
- **Margin:** orchestrator inflow `P_o x (1 - f)`; outflow `P_r x N + P_v + P_f` (full specialist prices). Budget = `P_o x (1 - f) - margin_floor`; the planner keeps `sum(specialist prices) <= budget` and caps fan-out `N` accordingly.
- **Demo prices:** orchestrator 0.50 USDC; specialists 0.05–0.10 USDC each. Margin can be ~0 — goal is volume + composability, not profit.
- **Working capital (key timing constraint):** the orchestrator is paid only after *it* delivers, but must `pay_order` specialists *during* the job. → Its AA wallet must hold pre-funded working-capital USDC `>= max single-job spend`, funded once and revolving (each completed job reimburses it).
- **Pre-accept checks:** at negotiation, verify requirements schema + AA balance `>=` projected spend (`is_insufficient_balance`) + projected spend `<=` budget; else `reject_negotiation`. Reserve funds per accepted job to avoid concurrent oversubscription.

---

## 7. Error Handling & SLA

| Scenario | Handling |
|---|---|
| Specialist rejects / SLA timeout | That sub-order's escrow **auto-refunds the orchestrator** (working capital recovered) → orchestrator fails over to an alternate catalog candidate (own/external, ≤1 retry). |
| Retry still fails + **critical step** (research/format) | Orchestrator `reject_order` on its own customer order → **customer auto-refunded**; never deliver garbage. |
| Failure + **non-critical step** (e.g. verify in `quick` depth) | Proceed with partial result; annotate `verdict=unverified` in deliverable meta. |
| Specialist delivered but schema-invalid/empty | Treat as failure → failover chain above. |
| Approaching orchestrator's own SLA | asyncio time budget: stop spawning new steps; deliver partial if acceptable, else reject. |
| Customer creates but never pays | pay deadline expires; no work done (work_fn only starts on ORDER_PAID); zero loss. |

- **SLA nesting:** orchestrator SLA must exceed `parallel research(max) + verify + format + overhead`. Demo values: specialists 5–10 min; orchestrator 60 min.
- **Crash recovery (MVP):** track in-flight order_ids in memory or small sqlite/json; on restart use `list_orders` / `list_negotiations` to resume. Single-process, best-effort — a known limitation.
- **Transparency:** every sub-order outcome (serviceId/order_id/price/verdict) is written into the deliverable `meta` — both a "verifiable" selling point and an aid for judges to confirm real A2A calls.

---

## 8. Agent Store Listing Flow (manual, in dashboard)

Performed at agent.croo.network, repeated for the orchestrator + 3 specialists (+1 demo customer agent):

1. **Register Agent:** name + avatar → system creates AA wallet + mints Agent DID → **copy & store API key `croo_sk_...`** (4–5 keys total).
2. **Configure each agent:** Description + 1–5 Skill Tags (research/verification/writing) → **Add Service:** name, **price USDC** (orchestrator 0.50 / specialists 0.05–0.10), SLA deadline (specialists 5–10 min, orchestrator 60 min), **Deliverable = Schema** (paste the §5 JSON schema), **Requirements = Schema**. Record each `serviceId`.
3. **Fund AA wallets** (to the **Agent AA Wallet Address**, not controller/executor): orchestrator gets working-capital USDC (≥ max single-job spend); demo customer gets a little USDC; the 3 specialists need none (they only receive).
4. **Back-fill config:** each agent's `croo_sk_` + serviceId into `.env` and `catalog.yaml`.
5. **Go Online:** run each provider process → status flips to Online → discoverable/hireable in the Store.

This zero-code step *is* the "Listed on Agent Store" requirement; README documents it with screenshots.

---

## 9. CAP Integration Call Map ("SDK methods used")

| Role | When | CAP call (Python) | Module |
|---|---|---|---|
| Provider | startup | `connect_websocket()` + `on(NEGOTIATION_CREATED)` / `on(ORDER_PAID)` | `provider_runtime` |
| Provider | on negotiation | `get_negotiation` → validate → `accept_negotiation` / `reject_negotiation` | `provider_runtime` / `cap_client` |
| Provider | on payment | run `work_fn` → (`upload_file` if large) → `deliver_order`; on failure `reject_order` | `provider_runtime` |
| Requester | hire / be paid | `negotiate_order` → `on(ORDER_CREATED)` → `pay_order` → `on(ORDER_COMPLETED)` → `get_delivery` (+ `get_download_url`) | `requester` / `cap_client` |
| Both | errors | `is_insufficient_balance` / `is_invalid_status` / `is_not_found` … | `cap_client` |

**On-chain verifiables for demo + "verifiable" value prop:** each order_id, the keccak256 delivery hash, and CAPVault escrow/settlement txs — all viewable on BaseScan (CAPCore `0xaD46…`, CAPVault `0x33EC…`).

---

## 10. Demo Script (≤5 min) & User Onboarding

### Minute-by-minute demo
- **0:00–0:30** One-line value: "Give the COO Agent a research topic; it hires and pays a team of specialist agents on-chain and returns a cited report." Show the orchestrator's Store listing.
- **0:30–1:30** Show all 4 agents Online + AA wallet balances; note gas is platform-sponsored.
- **1:30–3:30** Run `python examples/demo_client.py "<topic>"` (pays 0.50 USDC). Streaming logs show: plan → hire Research (3 parallel sub-orders) → pay → deliver → Verify → Format, with order_ids appearing.
- **3:30–4:20** Show the final cited report (report_markdown + per-claim verdicts) and the `meta.sub_orders` table (4 orders / prices / statuses).
- **4:20–5:00** Open BaseScan: CAPVault escrow + settlement txs. Close on "4 real on-chain settlements, 3 distinct counterparty agents, 0 gas."

### Normal-user onboarding (two tiers)
- **Tier 1 — Just hire it (no code; the "day-one real users" path):** find "COO Research Agent" on agent.croo.network (or via the Navigator), fund a wallet with a little USDC, place an order with a topic, receive a cited report. → real buyer wallets.
- **Tier 2 — Run it yourself (developers):** `git clone` → `pip install -e .` → copy `.env.example`, fill `ANTHROPIC_API_KEY` + the 4 `croo_sk_` keys + serviceIds (from your own §8 registration) → fund AA wallets → `make agents` (Procfile starts all 4 providers) → `make demo TOPIC="..."`. Ship `scripts/check_balances.py` preflight + README troubleshooting (insufficient balance / agent offline / SLA timeout).

---

## 11. Repo Structure

```
coo-agent/
├─ pyproject.toml      # croo-sdk, anthropic, pydantic, httpx, python-dotenv, pytest, pytest-asyncio
├─ README.md  LICENSE(MIT)  .env.example  catalog.yaml  Procfile
├─ coo_agent/
│  ├─ config.py  schemas.py  llm.py
│  ├─ cap_client.py        # croo-sdk wrapper (provider + requester)
│  ├─ provider_runtime.py  # generic provider loop (work_fn injection)
│  ├─ requester.py  catalog.py  planner.py  orchestrator.py
│  └─ specialists/{research,verify,format}.py
├─ examples/{run_orchestrator,run_research,run_verify,run_format,demo_client}.py
├─ scripts/check_balances.py
└─ tests/{test_schemas,test_planner,test_catalog,test_orchestrator_flow,conftest}.py
```

---

## 12. Testing Strategy

- **Unit:** schema validation; planner (goal + catalog + budget → bounded plan; fan-out & budget caps respected); catalog selection policy. Claude is stubbed for determinism.
- **Integration with `FakeCapClient`:** in-memory implementation of the cap_client interface simulating negotiate/accept/pay/deliver/events, with **fault injection** (specialist rejects, times out, returns bad schema). Exercises the full orchestrator logic deterministically — parallel research, verify dependency, failover, critical-step-fail → reject customer order, partial on non-critical, working-capital reservation. No chain, no USDC.
- **Real-CAP smoke:** one env-gated manual script runs a real single order on Base with tiny amounts to confirm the wrapper matches reality. Not in CI.
- **TDD** (red-green-refactor) throughout, enabled by the fast FakeCapClient.

### Phase 0 — SDK spike (must precede wrapper TDD)
We have not yet run croo-sdk. Doing TDD against an unverified external interface is risky. **First** run the quickstart against the real SDK (register a provider + requester, complete one order) to lock the real method names, async signatures, and event payloads; **then** build `cap_client` to that interface and write the FakeCapClient to match.

---

## 13. Anti-Sybil / Go-to-Market

- Low prices reduce buyer friction.
- `catalog.yaml` external slot + round-robin selection spread orders across counterparties and make it trivial to add partner teams' serviceIds.
- The orchestrator is listed and callable, so humans/agents can hire it via the Navigator → real buyer wallets. Ship `demo_client` + instructions so other teams can call it.
- **Targets:** ≥5 unique buyer wallets (recruit other participants/teammates to hire the orchestrator); ≥3 unique counterparty agents (the 3 specialists satisfy this by construction; adding external specialists/buyers strengthens it and reduces self-trade concentration).
- Note: in-house specialists mean orchestrator→specialist is intra-team ("self-trade-ish"); offset via (a) external buyers hiring the orchestrator, (b) optionally hiring 1 external specialist, (c) our specialists also serving external buyers. These are go-to-market actions; the architecture leaves room for all three.

---

## 14. Open Questions / Risks

1. **Exact croo-sdk interface** (method signatures, event payloads, config object) — resolve in Phase 0 spike.
2. **Platform fee rate `f`** and the **USDC token address** on Base — confirm from contracts/docs; affects budget math.
3. **Service discovery** — confirmed absent in SDK; if an undocumented list/search endpoint exists in the repo, the catalog could be auto-populated (nice-to-have, not required).
4. **Working-capital amount** — size it from final demo prices × max fan-out.
5. **Navigator hireability** — confirm a human can actually find + hire the orchestrator via the Store UI (needed for Tier-1 onboarding + real buyers).

---

## 15. Out of Scope (YAGNI)

- Arbitrary dynamic DAG planning (chose bounded hybrid skeleton).
- Multi-process/distributed durability, persistent job queue (single-process best-effort for MVP).
- Auto-discovery/auto-onboarding of external specialists (manual catalog entries).
- A web UI (terminal demo + Store listing suffice for the deadline).
- Profit optimization / dynamic pricing.
