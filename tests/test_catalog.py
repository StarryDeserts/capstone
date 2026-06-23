import textwrap
import pytest
from coo_agent.catalog import Catalog, CatalogEntry


def _write(tmp_path, body):
    p = tmp_path / "catalog.yaml"
    p.write_text(textwrap.dedent(body))
    return str(p)


VALID = """
    research:
      - { service_id: r1, price_usdc: 0.05, tags: [research] }
      - { service_id: r2, price_usdc: 0.07, tags: [research], external: true }
    verify:
      - { service_id: v1, price_usdc: 0.05, tags: [verification] }
    format:
      - { service_id: f1, price_usdc: 0.06, tags: [writing] }
"""


def test_load_and_candidates(tmp_path):
    cat = Catalog.load(_write(tmp_path, VALID))
    cands = cat.candidates("research")
    assert [c.service_id for c in cands] == ["r1", "r2"]
    assert cands[1].external is True


def test_load_missing_role_raises(tmp_path):
    with pytest.raises(ValueError):
        Catalog.load(_write(tmp_path, "research:\n  - { service_id: r1, price_usdc: 0.05, tags: [] }\n"))


def test_load_negative_price_raises(tmp_path):
    bad = VALID.replace("price_usdc: 0.05", "price_usdc: -1", 1)
    with pytest.raises(ValueError):
        Catalog.load(_write(tmp_path, bad))


def test_cheapest_policy(tmp_path):
    cat = Catalog.load(_write(tmp_path, VALID))
    assert cat.select("research", policy="cheapest").service_id == "r1"


def test_round_robin_rotates_and_excludes(tmp_path):
    cat = Catalog.load(_write(tmp_path, VALID))
    first = cat.select("research").service_id
    second = cat.select("research").service_id
    assert {first, second} == {"r1", "r2"}
    assert cat.select("research", exclude={"r1", "r2"}) is None
