"""Exact-order collection lookup and admin owner-filter permissions."""

from Auth import create_jwt
from data.DB import OrderPriceAdjustmentTable, OrderQuoteVersionTable
from services import receivable_service as service
from tests.unit.test_order_receipt_revision import ADMIN, _add_receipt_history, _seed_world
from tests.unit.test_receipt_settlement import SALES, _body


FINANCE = {"user_id": 7, "name": "财务测试", "role": "finance"}


def _get(client, path, operator, **filters):
    response = client.get(
        path,
        headers={"x-token": create_jwt(operator)},
        query_string=filters,
    )
    assert response.status_code == 200
    return response.get_json()


def test_exact_order_lookup_preserves_collectible_balance_and_quote_owner_scope(
    client, setup_test_database,
):
    session = setup_test_database
    customer, orders, _ = _seed_world(session, order_count=2)
    other_quote = session.query(OrderQuoteVersionTable).filter_by(order_uid=orders[1].uid).one()
    other_quote.quoter_id = ADMIN["user_id"]
    session.commit()

    path = "/api/receivables/orders"
    own = _get(client, path, SALES, order_uid=orders[0].uid, s=1)
    assert own["total"] == 1
    assert own["data"][0]["uid"] == orders[0].uid
    assert own["data"][0]["available_amount"] == 132
    assert _get(client, path, ADMIN, order_uid=orders[1].uid)["total"] == 1
    assert _get(client, path, SALES, order_uid=orders[1].uid, owner_id=1)["total"] == 0
    assert _get(client, path, ADMIN, order_uid=orders[1].uid, owner_id=3)["total"] == 0
    assert _get(client, path, ADMIN, order_uid="revision-order")["total"] == 0

    service.create_receipt(_body(customer, orders[:1], [132], settlement_status="settled"), SALES)
    assert _get(client, path, SALES, order_uid=orders[0].uid)["total"] == 0


def test_receipt_owner_filter_uses_creator_before_pagination_without_broadening_sales_scope(
    client, setup_test_database,
):
    customer, orders, _ = _seed_world(setup_test_database)
    for creator in (SALES, SALES, ADMIN):
        service.create_receipt(_body(customer, orders, [10], settlement_status="unsettled"), creator)

    path = "/api/receipts"
    assert _get(client, path, ADMIN)["total"] == 3
    admin_own = _get(client, path, ADMIN, owner_id=1)
    assert admin_own["total"] == 1
    assert admin_own["data"][0]["creator_id"] == 1
    assert _get(client, path, ADMIN, owner_id=999)["total"] == 0
    assert _get(client, path, FINANCE)["total"] == 3
    first = _get(client, path, FINANCE, owner_id=3, s=1)
    second = _get(client, path, FINANCE, owner_id=3, s=1, p=2)
    assert first["total"] == second["total"] == 2
    assert {item["creator_id"] for item in first["data"] + second["data"]} == {3}
    assert first["data"][0]["id"] != second["data"][0]["id"]
    assert _get(client, path, SALES, owner_id=1)["total"] == 2


def test_adjustment_owner_and_exact_order_filters_use_current_quote_scope(
    client, setup_test_database,
):
    session = setup_test_database
    customer, orders, _ = _seed_world(session, order_count=2)
    for order in orders:
        _add_receipt_history(session, customer, order)
        service.create_order_quote(order.uid, {"unit_price": 13, "surcharge": 0}, SALES)
    # Collection follows effective quote ownership even if the order assignment differs.
    other_quote = session.query(OrderQuoteVersionTable).filter_by(
        order_uid=orders[1].uid, is_final=True,
    ).one()
    other_quote.quoter_id = ADMIN["user_id"]
    other_quote.quoter_name = ADMIN["name"]
    session.commit()

    path = "/api/receivable-adjustments"
    assert _get(client, path, ADMIN)["total"] == 2
    assert _get(client, path, FINANCE)["total"] == 2
    admin_own = _get(client, path, ADMIN, owner_id=1, order_uid=orders[1].uid)
    assert admin_own["total"] == 1
    assert admin_own["data"][0]["order_uid"] == orders[1].uid
    assert admin_own["data"][0]["available_amount"] == 12
    assert _get(client, path, FINANCE, owner_id=3)["total"] == 1
    assert _get(client, path, ADMIN, order_uid=orders[1].uid, owner_id=3)["total"] == 0
    assert _get(client, path, ADMIN, order_uid="revision-order")["total"] == 0
    sales = _get(client, path, SALES, owner_id=1)
    assert sales["total"] == 1
    assert sales["data"][0]["order_uid"] == orders[0].uid
    assert _get(client, path, SALES, order_uid=orders[1].uid, owner_id=1)["total"] == 0

    other_adjustment = session.query(OrderPriceAdjustmentTable).filter_by(order_uid=orders[1].uid).one()
    response = client.get(
        f"{path}/{other_adjustment.id}",
        headers={"x-token": create_jwt(SALES)},
    )
    assert response.status_code == 403
