import importlib


def test_check_balances_importable():
    m = importlib.import_module("scripts.check_balances")
    assert callable(m.main)
