# CAP / croo SDK — observed interface notes

Deliverable for **Task 18** (human gate). Captures the real `croo` SDK surface so
**Task 20** (`RealCapClient`) can be built against fact, not guesswork.

Status legend:
- ✅ **CONFIRMED (offline)** — read directly from the installed `croo` package via
  introspection (`examples/spike_dry.py`). Authoritative; no live run needed.
- 🔎 **CONFIRM (live)** — claimed by docs/memory; verify by watching one order settle.
- ❓ **OBSERVE (live)** — unknown; must be read off a live run.
- ⛔ **GAP** — capability appears missing; needs a workaround.

The installed SDK imports as `croo` (NOT `croo_sdk`). Regenerate the offline section
anytime with: `uv run python -m examples.spike_dry`.

---

## A. Mainnet constants ✅ / 🔎

| Item | Value | Status |
|---|---|---|
| Chain | Base Mainnet, chainId **8453** | ✅ |
| USDC (settlement token) | `0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913` (6 decimals) | ✅ const |
| API URL | `https://api.croo.network` | 🔎 |
| WS URL | `wss://api.croo.network/ws` | 🔎 |
| CAPCore (state) | `0xaD46f1Eba2fe9cBB689D2874a52039192F2ac821` | 🔎 |
| CAPVault (escrow) | `0x33ECdcC8dD32330ec5a62AB1986F25ED5B5D170d` | 🔎 |
| CROOValidationModule | `0xfCc7eefd6D22bC6a4F35B467928ecAF738d0B3b8` | 🔎 |
| Gas | 0% sponsored during launch (ERC-4337, EntryPoint v0.7, Biconomy Nexus) | 🔎 |

---

## B. SDK surface — CONFIRMED offline ✅

### Construction
```python
from croo import AgentClient, Config
client = AgentClient(Config(base_url=API_URL, ws_url=WS_URL, rpc_url=RPC_URL), sdk_key)
```
- ⚠️ Field is **`base_url`**, not `api_url`. Our `Config` (config.py) uses `api_url` →
  `RealCapClient` must map `config.api_url -> Config(base_url=...)`.
- `ws_url` / `rpc_url` default to `""`.

### Methods — all `async` (await directly; no thread-pool wrapping needed)
```
async negotiate_order(req: NegotiateOrderRequest) -> Negotiation
async accept_negotiation(negotiation_id) -> AcceptNegotiationResult
async accept_negotiation_with_fund_address(negotiation_id, provider_fund_address) -> AcceptNegotiationResult
async pay_order(order_id) -> PayOrderResult
async deliver_order(order_id, req: DeliverOrderRequest) -> DeliverOrderResult
async reject_order(order_id, reason) -> None
async reject_negotiation(negotiation_id, reason) -> None
async get_order(order_id) -> Order
async get_negotiation(negotiation_id) -> Negotiation
async get_delivery(order_id) -> Delivery
async list_orders(opts: ListOptions | None) -> list[Order]
async list_negotiations(opts: ListOptions | None) -> list[Negotiation]
async connect_websocket() -> EventStream
async upload_file(file_name, body: bytes | BinaryIO) -> str   # returns object_key
async get_download_url(object_key) -> str
async close() -> None
```

### EventStream — callback-based, NOT an async iterator
```
async connect()                                  # call AFTER registering handlers
sync  on(event_type: str, handler: Callable[[Event], None])
sync  on_any(handler: Callable[[Event], None])
sync  err() -> Exception | None
async close()
```
- `__aiter__` is **False** → there is no `async for ev in stream`.
- **Task 20 bridge:** register `on_any` → push each `Event` into an `asyncio.Queue`,
  expose an async generator over the queue. Handler is a **sync** callback that may
  fire off-loop → use `loop.call_soon_threadsafe(queue.put_nowait, ev)`.

### EventType wire values (exact strings on `Event.type` / `.raw`)
```
NEGOTIATION_CREATED  = 'order_negotiation_created'
NEGOTIATION_REJECTED = 'order_negotiation_rejected'
NEGOTIATION_EXPIRED  = 'order_negotiation_expired'
ORDER_CREATED        = 'order_created'
ORDER_PAID           = 'order_paid'
ORDER_COMPLETED      = 'order_completed'
ORDER_REJECTED       = 'order_rejected'
ORDER_EXPIRED        = 'order_expired'
```

### Dataclass fields (→ map to our schemas in Task 20)
- **Event**: `type, raw(dict), negotiation_id, order_id, requester_agent_id,
  provider_agent_id, service_id, status, reason`
- **Negotiation**: `negotiation_id, service_id, requester_agent_id, provider_agent_id,
  requirements(str), status, reject_reason, metadata, expires_at, created_time,
  updated_time, fund_amount, fund_token, provider_fund_address`
- **Order**: `order_id, negotiation_id, chain_order_id, service_id,
  requester_agent_id, provider_agent_id, buyer_user_id, requester_wallet_address,
  provider_wallet_address, price(str), payment_token, delivery_window, status,
  reject_reason, create_tx_hash, pay_tx_hash, deliver_tx_hash, reject_tx_hash,
  clear_tx_hash, sla_deadline, pay_deadline, created_time, updated_time, created_at,
  paid_at, delivered_at, rejected_at, expired_at, fee_amount, fund_amount, fund_token,
  provider_fund_address`
- **AcceptNegotiationResult**: `negotiation, order` — accept returns the created `Order`
  synchronously (so `order_id` is available without waiting for the WS event).
- **PayOrderResult**: `order, tx_hash`
- **DeliverOrderRequest**: `deliverable_type(str), deliverable_schema(str), deliverable_text(str)`
- **DeliverOrderResult**: `order, delivery, tx_hash`
- **Delivery**: `delivery_id, order_id, provider_agent_id, deliverable_type,
  deliverable_schema, deliverable_text, content_hash, status, submitted_at,
  verified_at, created_time, updated_time`

### Request payloads are strings (JSON-encode our dicts)
```
NegotiateOrderRequest(service_id, requirements='', metadata='', requester_agent_id='',
                      fund_amount='', fund_token='')
```
- `requirements` and `deliverable_text` are **`str`** → `json.dumps(...)` our payloads
  on the way out, `json.loads(...)` on the way in.
- `fund_amount` is a **str** (e.g. `"0.05"`); `fund_token` is the USDC address above.

### Error surface (RealCapClient classification)
- Exceptions: `croo.APIError`, `croo.InsufficientBalanceError`.
- Predicates (pass the caught exception): `is_unauthorized, is_forbidden, is_not_found,
  is_invalid_params, is_invalid_status, is_insufficient_balance`.
- Balance precheck primitive (**no** numeric `get_balance`):
  `async croo.balance.check_erc20_balance(rpc_url, wallet_addr, token_addr, price_str)`
  — raises `InsufficientBalanceError` if short. `croo.balance.DEFAULT_RPC_URL` exists.

---

## C. Runtime semantics

### C1. RESOLVED — from SDK status enums + a live error/auth probe ✅

Status wire-strings come straight from the SDK enums (`croo.OrderStatus` etc.) — these
ARE the authoritative values, no live order needed:

- **NegotiationStatus**: `pending`, `accepted`, `rejected`, `expired`
- **OrderStatus**: `created`, `paid`, `completed`, `rejected`, `expired` **plus transient
  on-chain states** `creating`, `paying`, `delivering`, `rejecting` and failure states
  `create_failed`, `pay_failed`, `deliver_failed`.
- **DeliveryStatus**: `submitted`, `accepted`, `rejected`
- ⚠️ **Task 20 must treat `creating/paying/delivering/rejecting` as in-flight** (the
  on-chain tx is mid-flight) — poll `get_order`/await the WS terminal event rather than
  assuming `accept`/`pay`/`deliver` returns a terminal status synchronously. The `*_failed`
  states are terminal failures.

Confirmed against the **live mainnet API** (orchestrator key, `examples/spike_dry.py`):
- ✅ **Auth:** invalid SDK key → WS handshake `HTTP 401`; REST → `APIError SDK_KEY_INVALID
  (code=401)`, `is_unauthorized() == True`. Valid key → WS connects.
- ✅ **Error codes + classification** (real `APIError(code, http, message)`):
  `SDK_KEY_INVALID` 401→`is_unauthorized`; `SERVICE_NOT_FOUND` 404→`is_not_found`;
  `INVALID_PARAMETERS` 400→(`is_invalid_params`).
- ✅ **`list_orders` requires `ListOptions(role=...)`** — `list_orders(None)` →
  `INVALID_PARAMETERS: role must be 'buyer' or 'provider'`. So always pass
  `ListOptions(role="buyer")` (or `"provider"`); `agent_id`, `status`, `page/page_size` optional.
- ✅ **negotiate against an unknown service** → `SERVICE_NOT_FOUND` 404 (not a self-hire
  error). The provider must own a *published, resolvable* service id.

### C2. STILL needs ONE live settled order ❓ (defer until ready to spend pennies)

Only obtainable by driving accept→pay→deliver→settle on a real, hireable service:

- 🔎 **`pay_order` auto-approves USDC** (no separate ERC-20 approve). Confirm on first pay.
- ❓ **Fee rate**: `Order.fee_amount` vs `price` on a settled order → `____%` (feeds
  `PLATFORM_FEE_RATE`/`compute_budget`).
- ❓ **Gas in practice**: do `create_tx_hash`/`pay_tx_hash` populate without the AA wallet
  spending ETH? (confirms 0%-gas launch window).
- ❓ **`content_hash`**: `keccak256(deliverable_text)`? encoding? `__________`
- ❓ **Fundable wallet**: which field is the AA wallet to fund — `requester_wallet_address`
  / `provider_fund_address`? Where is *my own* AA address surfaced before any order exists?
  (likely the dashboard, not the SDK) `__________`
- ❓ **`deliverable_type` / `deliverable_schema` accepted values**: free string? MIME?
  schema name? What does the platform validate? `__________`
- ❓ **Deadlines**: `delivery_window` units (seconds?); `sla_deadline`/`pay_deadline`
  format (ISO? epoch?). `__________`
- ❓ **Event ordering/timing**: observed sequence `__________ → __________ → __________`.

### C3. BLOCKER hit during the spike

The configured `COO_ORCHESTRATOR_SERVICE_ID` (`svc-new-…`) returns `SERVICE_NOT_FOUND`.
Need ONE of: (a) the correct/published orchestrator service id, or (b) a *second* real
agent (or an external team's service id) so we can observe a successful requester→provider
negotiation — which we need for anti-sybil anyway. Until then C2 stays blank.

---

## D. Known gap ⛔

- **Programmatic service discovery.** `AgentClient` exposes `list_orders` /
  `list_negotiations` but **no `list_services` / `search_services`**. The quickstart
  targets a known `CROO_TARGET_SERVICE_ID`. An orchestrator that hires *arbitrary*
  agents needs a discovery API. To confirm on the live gate:
  - Is there a REST endpoint (e.g. `GET {api_url}/services?...`) not surfaced in the SDK?
  - Or is discovery only via the Agent Store UI (→ we hard-code a curated catalog of
    serviceIds in `catalog.yaml`, which is what our design already does)?
  - **Working assumption for the hackathon:** curated `catalog.yaml` of known serviceIds
    (incl. ≥2 external teams') — discovery API is a nice-to-have, not a blocker.

---

## E. Implications for `RealCapClient` (Task 20)

1. Map our `Config.api_url -> croo.Config(base_url=...)`; pass `ws_url`, `rpc_url` through.
2. SDK is fully async → implement the `CapClient` Protocol by awaiting SDK methods directly.
3. **Event delivery is the real work:** bridge `EventStream.on_any` (sync callback,
   possibly off-loop) → `asyncio.Queue` → async iterator, so `ProviderRuntime`'s
   awaited event loop keeps working unchanged. Connect WS *after* registering handlers.
4. JSON-encode `requirements`/`deliverable_text`; decode on read.
5. Use `croo.balance.check_erc20_balance` for the working-capital precheck (it raises;
   wrap to our precheck's boolean/raise contract). Resolve the wallet address from the
   field confirmed in §C.
6. Classify errors via the `is_*` predicates → our retry/failover decisions
   (`is_insufficient_balance` → abort+refund path; `is_invalid_status` → race, re-`get_order`).
7. Translate `Order.status` / `Negotiation.status` wire strings (§C) into our enums.
