.PHONY: install agents demo test check balances

install:
	pip install -e ".[dev]"

# Run all four provider loops together (orchestrator + 3 specialists).
agents:
	honcho start

# Fire one customer order at the orchestrator (optional: make demo TOPIC="...").
demo:
	python -m examples.demo_client "$(TOPIC)"

test:
	pytest -q

# Full local gate: compile-check then the unit suite (no chain, no network).
check:
	python -m compileall -q coo_agent examples scripts
	pytest -q

balances:
	python -m scripts.check_balances
