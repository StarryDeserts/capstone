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
