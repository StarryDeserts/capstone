import pytest
from coo_agent.config import Config, AgentCreds, compute_budget

BASE_ENV = {
    "ANTHROPIC_API_KEY": "sk-ant-x",
    "CROO_API_URL": "https://api.croo.network",
    "CROO_WS_URL": "wss://api.croo.network/ws",
    "CLAUDE_MODEL": "claude-opus-4-7",
    "PLATFORM_FEE_RATE": "0.1",
    "MARGIN_FLOOR": "0.0",
    "COO_ORCHESTRATOR_SK": "croo_sk_o", "COO_ORCHESTRATOR_SERVICE_ID": "svc_o",
    "RESEARCH_SK": "croo_sk_r", "RESEARCH_SERVICE_ID": "svc_r",
    "VERIFY_SK": "croo_sk_v", "VERIFY_SERVICE_ID": "svc_v",
    "FORMAT_SK": "croo_sk_f", "FORMAT_SERVICE_ID": "svc_f",
    "DEMO_CUSTOMER_SK": "croo_sk_d",
}


def test_from_env_populates_agents():
    c = Config.from_env(BASE_ENV)
    assert c.agents["research"].sk_key == "croo_sk_r"
    assert c.agents["research"].service_id == "svc_r"
    assert c.fee_rate == 0.1 and c.model == "claude-opus-4-7"
    assert c.orchestrator_price == pytest.approx(0.50)  # env default


def test_from_env_missing_required_key_raises():
    env = dict(BASE_ENV); del env["ANTHROPIC_API_KEY"]
    with pytest.raises(KeyError):
        Config.from_env(env)


def test_optional_rpc_defaults_none():
    assert Config.from_env(BASE_ENV).rpc_url is None


def test_compute_budget():
    assert compute_budget(0.50, 0.1, 0.0) == pytest.approx(0.45)
    assert compute_budget(0.50, 0.0, 0.05) == pytest.approx(0.45)
