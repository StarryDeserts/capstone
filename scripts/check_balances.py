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
