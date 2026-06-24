from __future__ import annotations

import asyncio
import signal

from coo_agent.config import Config
from examples._bootstrap import build_cap_client


async def main() -> None:
    """Bring the orchestrator agent ONLINE by holding a WebSocket connection.

    A CROO agent flips from `draft` to `online` only while its SDK keeps a live
    WS handshake (heartbeat); a `draft`/`offline` agent's services return
    SERVICE_NOT_FOUND. This probe does nothing but connect and hold — no LLM,
    no catalog, no orders, 0 USDC — so the "can it go online" signal is isolated
    from the orchestrator's business logic. Verify status at agent.croo.network.
    """
    config = Config.from_env()
    creds = config.agents["orchestrator"]
    cap = build_cap_client(creds.sk_key, config)

    await cap.connect()
    print(f"[go_online] WS connected as orchestrator; service={creds.service_id}")
    print(f"[go_online] api={config.api_url} ws={config.ws_url}")
    print("[go_online] agent should now flip draft -> online; verify at "
          "agent.croo.network -> Configure (status: online, Visible in Store: Yes)")
    print("[go_online] holding the connection open to keep the heartbeat alive; "
          "Ctrl-C to stop (agent returns to offline on exit)")

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # add_signal_handler is POSIX-only
            pass
    try:
        await stop.wait()
    finally:
        await cap.close()
        print("[go_online] connection closed; agent returns to offline")


if __name__ == "__main__":
    asyncio.run(main())
