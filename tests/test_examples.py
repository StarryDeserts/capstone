import importlib

import pytest

from examples._bootstrap import substitute_env, load_catalog

EXAMPLE_MODULES = [
    "examples._bootstrap",
    "examples.run_orchestrator",
    "examples.run_research",
    "examples.run_verify",
    "examples.run_format",
    "examples.demo_client",
    "examples.spike_dry",
]


def test_substitute_env_resolves_brace_and_bare():
    out = substitute_env("a: ${FOO}\nb: $BAR\nc: ${MISSING}", {"FOO": "x", "BAR": "y"})
    assert "a: x" in out and "b: y" in out
    assert "${MISSING}" in out  # safe_substitute leaves unknowns intact


def test_load_catalog_substitutes_service_ids(tmp_path):
    p = tmp_path / "catalog.yaml"
    p.write_text(
        'research:\n  - { service_id: "${RESEARCH_SERVICE_ID}", price_usdc: 0.05 }\n'
        'verify:\n  - { service_id: "v", price_usdc: 0.05 }\n'
        'format:\n  - { service_id: "f", price_usdc: 0.06 }\n',
        encoding="utf-8",
    )
    cat = load_catalog(str(p), {"RESEARCH_SERVICE_ID": "svc_r"})
    assert cat.select("research").service_id == "svc_r"


@pytest.mark.parametrize("mod", EXAMPLE_MODULES)
def test_example_module_imports_without_adapter(mod):
    m = importlib.import_module(mod)
    if mod != "examples._bootstrap":
        assert callable(getattr(m, "main"))
