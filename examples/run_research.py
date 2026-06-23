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
