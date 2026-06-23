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
