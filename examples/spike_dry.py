"""Free, zero-cost dry-spike against the real `croo` SDK.

Purpose: observe the SDK that ``RealCapClient`` (Task 20) must wrap — method
signatures, async-ness, event wire names, dataclass field names, and error
classification — BEFORE spending anything on Base mainnet. The static section
needs no network and no credentials; ``--live`` additionally drives a single
negotiate-then-reject exchange.

This deliberately uses the raw `croo` SDK directly, NOT ``examples._bootstrap``'s
``build_cap_client`` — that helper imports the not-yet-built ``RealCapClient``.
The whole point of the spike is to look *under* our abstraction at the SDK it
will be built on top of.

Cost guarantee: this script NEVER calls ``accept_negotiation`` (which would
``createOrder`` on-chain) or ``pay_order`` (which would escrow USDC). The live
path only negotiates (an off-chain proposal) and then rejects it. No USDC moves.

Usage::

    uv run python -m examples.spike_dry          # static introspection only (offline)
    uv run python -m examples.spike_dry --live   # also negotiate+reject (needs real creds)

Live path reads from env (or .env): CROO_API_URL, CROO_WS_URL, BASE_RPC_URL,
SPIKE_SERVICE_ID (or COO_ORCHESTRATOR_SERVICE_ID), and one agent *_SK.
"""
from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import os

import croo
from croo import AgentClient, Config, EventType, NegotiateOrderRequest

# Base mainnet USDC (6 decimals) — the token CROO settles in.
USDC_BASE_MAINNET = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"

# Methods RealCapClient (Task 20) must wrap; async-ness decides whether it can
# await them directly (it can — they are all coroutines).
_CLIENT_METHODS = [
    "negotiate_order", "accept_negotiation", "accept_negotiation_with_fund_address",
    "pay_order", "deliver_order", "reject_order", "reject_negotiation",
    "get_order", "get_negotiation", "get_delivery", "list_orders",
    "connect_websocket", "close", "upload_file", "get_download_url",
]

_DATACLASSES = [
    "Event", "Negotiation", "Order", "AcceptNegotiationResult",
    "PayOrderResult", "DeliverOrderRequest", "DeliverOrderResult", "Delivery",
]

_SK_ENV_ORDER = (
    "DEMO_CUSTOMER_SK", "COO_ORCHESTRATOR_SK", "RESEARCH_SK", "VERIFY_SK", "FORMAT_SK",
)


def dump_static_interface() -> None:
    print("# croo SDK — static interface (zero network, zero cost)")
    print(f"version:  {getattr(croo, '__version__', '?')}")
    print(f"location: {os.path.dirname(croo.__file__)}")

    print("\n## construction")
    print(f"  AgentClient{inspect.signature(AgentClient.__init__)}")
    print(f"  Config{inspect.signature(Config)}")

    print("\n## AgentClient methods (async-ness drives RealCapClient's await/bridge)")
    for name in _CLIENT_METHODS:
        fn = getattr(AgentClient, name, None)
        if fn is None:
            print(f"  <MISSING> {name}")
            continue
        kind = "async" if inspect.iscoroutinefunction(fn) else "sync "
        try:
            sig = str(inspect.signature(fn))
        except (TypeError, ValueError):
            sig = "(?)"
        print(f"  {kind} {name}{sig}")

    print("\n## EventType wire values (what the WS/raw payloads carry)")
    for n in sorted(n for n in dir(EventType) if not n.startswith("_")):
        print(f"  {n} = {getattr(EventType, n)!r}")

    print("\n## EventStream protocol (callback-based — NOT an async iterator)")
    es = croo.EventStream
    print(f"  __aiter__={hasattr(es, '__aiter__')}  -> bridge .on_any() into an asyncio.Queue")
    for n in ("connect", "on", "on_any", "err", "close"):
        fn = getattr(es, n, None)
        if fn is None:
            continue
        kind = "async" if inspect.iscoroutinefunction(fn) else "sync "
        print(f"  {kind} {n}{inspect.signature(fn)}")

    print("\n## key dataclasses (field names -> our schema mapping in Task 20)")
    for cls_name in _DATACLASSES:
        cls = getattr(croo, cls_name, None)
        fields = getattr(cls, "__dataclass_fields__", None)
        names = ", ".join(fields.keys()) if fields else "<not a dataclass>"
        print(f"  {cls_name}: {names}")

    print("\n## error surface (RealCapClient classification)")
    predicates = [n for n in dir(croo.errors) if n.startswith("is_")]
    print(f"  exceptions: APIError, InsufficientBalanceError")
    print(f"  predicates: {', '.join(predicates)}")
    bal = croo.balance.check_erc20_balance
    print(f"  precheck:   croo.balance.check_erc20_balance{inspect.signature(bal)}")
    print(f"              (async; raises InsufficientBalanceError — no numeric get_balance)")


def _pick_sk() -> tuple[str, str]:
    for env_name in _SK_ENV_ORDER:
        sk = os.environ.get(env_name, "")
        if sk:
            return env_name, sk
    return "", ""


def _classify(exc: Exception) -> None:
    flags = []
    for n in ("is_unauthorized", "is_forbidden", "is_not_found",
              "is_invalid_params", "is_invalid_status", "is_insufficient_balance"):
        pred = getattr(croo.errors, n, None)
        if pred is None:
            continue
        try:
            if pred(exc):
                flags.append(n)
        except Exception:
            pass
    print(f"    classified as: {flags or ['<none matched>']}")


async def live_negotiate_only() -> None:
    """Connect WS, negotiate once, then reject — never accept, never pay."""
    api_url = os.environ.get("CROO_API_URL", "")
    ws_url = os.environ.get("CROO_WS_URL", "")
    rpc_url = os.environ.get("BASE_RPC_URL", "")
    service_id = (os.environ.get("SPIKE_SERVICE_ID")
                  or os.environ.get("COO_ORCHESTRATOR_SERVICE_ID", ""))
    env_name, sk = _pick_sk()

    print("\n# live negotiate-only spike (NO accept, NO pay — zero USDC)")
    if not (api_url and sk and service_id):
        print("  SKIPPED — need CROO_API_URL + a *_SK + SPIKE_SERVICE_ID "
              "(or COO_ORCHESTRATOR_SERVICE_ID).")
        print(f"  have: CROO_API_URL={'yes' if api_url else 'no'}  "
              f"sk={env_name or 'none'}  service_id={'yes' if service_id else 'no'}")
        return

    print(f"  using sk={env_name}  service_id={service_id}")
    client = AgentClient(Config(base_url=api_url, ws_url=ws_url, rpc_url=rpc_url), sk)

    events: list = []
    stream = None
    neg = None
    try:
        try:
            stream = await client.connect_websocket()
            stream.on_any(lambda ev: events.append(ev))
            await stream.connect()
            print("  websocket: connected")
        except Exception as exc:
            print(f"  websocket: FAILED {type(exc).__name__}: {exc}")

        req = NegotiateOrderRequest(
            service_id=service_id,
            requirements=json.dumps({"topic": "dry-spike — do not fulfill",
                                     "depth": "quick"}),
            fund_amount="0.05",
            fund_token=USDC_BASE_MAINNET,
        )
        try:
            neg = await client.negotiate_order(req)
            print(f"  negotiate_order OK -> negotiation_id={neg.negotiation_id} "
                  f"status={neg.status!r} expires_at={neg.expires_at!r}")
            print(f"    full negotiation: {neg!r}")
        except Exception as exc:
            print(f"  negotiate_order FAILED {type(exc).__name__}: {exc}")
            _classify(exc)

        await asyncio.sleep(2.0)  # let NEGOTIATION_CREATED surface on the WS
        for ev in events:
            print(f"  event: type={ev.type!r} negotiation_id={ev.negotiation_id!r} "
                  f"order_id={ev.order_id!r} status={ev.status!r}")
        if not events:
            print("  (no websocket events within 2s)")
    finally:
        if neg is not None:
            try:
                await client.reject_negotiation(neg.negotiation_id, "dry-spike cleanup")
                print("  reject_negotiation OK (cleaned up)")
            except Exception as exc:
                print(f"  reject_negotiation FAILED {type(exc).__name__}: {exc}")
        if stream is not None:
            try:
                await stream.close()
            except Exception:
                pass
        try:
            await client.close()
        except Exception:
            pass


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Zero-cost dry-spike of the croo SDK (never pays).")
    parser.add_argument("--live", action="store_true",
                        help="also negotiate+reject against a real service (needs creds)")
    args = parser.parse_args()

    try:
        from dotenv import load_dotenv
        load_dotenv()
    except Exception:
        pass

    dump_static_interface()
    if args.live:
        asyncio.run(live_negotiate_only())
    else:
        print("\n(pass --live to also drive a real negotiate+reject; it never pays)")


if __name__ == "__main__":
    main()
