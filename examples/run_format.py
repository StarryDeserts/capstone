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
