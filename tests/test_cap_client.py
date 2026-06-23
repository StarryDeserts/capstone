from coo_agent.cap_client import (
    CapError, is_insufficient_balance, is_invalid_status, is_not_found,
    OrderStatus, CapEvent, Order, Negotiation, Delivery, CapClient,
)


def test_error_helpers_classify_by_code():
    assert is_insufficient_balance(CapError("x", code="insufficient_balance"))
    assert not is_insufficient_balance(CapError("x", code="other"))
    assert is_invalid_status(CapError("x", code="invalid_status"))
    assert is_not_found(CapError("x", code="not_found"))
    assert not is_not_found(ValueError("x"))


def test_enum_values():
    assert OrderStatus.paid.value == "paid"
    assert CapEvent.ORDER_COMPLETED.value == "ORDER_COMPLETED"


def test_domain_types_construct():
    o = Order(order_id="o", service_id="s", status=OrderStatus.created,
              price_usdc=0.1, requirements={}, negotiation_id="n")
    assert o.status is OrderStatus.created
    assert Negotiation("n", "s", "did", {}).service_id == "s"
    assert Delivery("o", {"a": 1}).deliverable == {"a": 1}


def test_protocol_is_importable():
    assert CapClient is not None
