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
