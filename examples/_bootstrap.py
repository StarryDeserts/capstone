from __future__ import annotations

import os
import tempfile
from string import Template
from typing import Mapping, Optional

from coo_agent.cap_client import CapClient
from coo_agent.catalog import Catalog
from coo_agent.config import Config
from coo_agent.llm import LLM


def substitute_env(text: str, env: Mapping[str, str]) -> str:
    return Template(text).safe_substitute(env)


def load_catalog(path: str, env: Optional[Mapping[str, str]] = None) -> Catalog:
    env = dict(os.environ if env is None else env)
    with open(path, "r", encoding="utf-8") as fh:
        rendered = substitute_env(fh.read(), env)
    # Render to a temp file so Catalog.load stays the single YAML parser/validator.
    tmp = tempfile.NamedTemporaryFile(
        "w", suffix=".yaml", delete=False, encoding="utf-8")
    try:
        tmp.write(rendered)
        tmp.close()
        return Catalog.load(tmp.name)
    finally:
        os.unlink(tmp.name)


def build_llm(config: Config) -> LLM:
    from anthropic import AsyncAnthropic  # lazy: keep import-smoke independent

    client = AsyncAnthropic(api_key=config.anthropic_api_key)
    return LLM(client, config.model)


def build_cap_client(sk_key: str, config: Config) -> CapClient:
    # Lazy import: the real adapter lands in Task 20. Deferring it here lets every
    # example module import cleanly before the adapter exists.
    from coo_agent.real_cap import RealCapClient

    return RealCapClient(sk_key=sk_key, api_url=config.api_url,
                         ws_url=config.ws_url, rpc_url=config.rpc_url)
