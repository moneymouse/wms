from decimal import Decimal

import pytest

from Auth import create_jwt, hash_password
from data.DB import (
    CargoTable,
    ExcelTemplateTable,
    OrderQuoteVersionTable,
    OrderTable,
    PaymentReceiptTable,
    RECEIPT_LOCKED_MESSAGE,
    TransportationModeTable,
)
from data.packing.PackingList import PackingListTable
from data.customer.Customer import CustomerTable
from data.user.Role import RoleTable
from data.user.User import UserTable
from services import receivable_service


def _headers(token):
    return {"x-token": token, "Content-Type": "application/json"}


def _finance_token(user_id=7):
    return create_jwt({
        "user_id": user_id,
        "name": "财务测试",
        "phone": "13800000007",
        "role": "finance",
    })


def _salesperson_token(user_id=8, name="其他业务员"):
    return create_jwt({
        "user_id": user_id,
        "name": name,
        "phone": f"138000000{user_id}",
        "role": "salesperson",
    })


def _seed_order(session):
    salesperson_role = RoleTable(name="salesperson", label="业务员")
    users = [
        UserTable(id=1, phone="13800000001", name="管理员测试", password=hash_password("x"), status="approved"),
        UserTable(id=3, phone="13800000003", name="业务员测试", password=hash_password("x"), status="approved"),
        UserTable(id=7, phone="13800000007", name="财务测试", password=hash_password("x"), status="approved"),
    ]
    users[1].roles = [salesperson_role]
    customer = CustomerTable(name="测试客户")
    order = OrderTable(
        uid="erp-order-1",
        order_id="ERP-001",
        customer_name="测试客户",
        transportation="测试渠道",
        salesman_id=3,
        archive=False,
        create_date="2026-08-27 09:00:00",
    )
    order.customers = [customer]
    cargo = CargoTable(
        uid="erp-cargo-1",
        target_order_uid=order.uid,
        weight=10.5,
        archive=False,
        create_date="2026-08-27 09:00:00",
    )
    mode = TransportationModeTable(
        name="测试渠道",
        channel_group="test",
        cost=10,
        min_price=11,
        archive=False,
        create_date="2026-08-27 09:00:00",
    )
    template = ExcelTemplateTable(
        mode_key="test_supplier",
        label="测试供应商",
        template_type="column",
        config='{"columns":["订单号"],"reference_table":{"订单号":"order_id"}}',
        requires_valid_quote=True,
        archive=False,
    )
    session.add_all(users + [customer, order, cargo, mode, template])
    session.commit()
    return customer, order, cargo


def test_receivable_uses_weight_rounded_up_to_whole_kilograms():
    assert receivable_service.billing_weight("43.2") == Decimal("44")
    assert receivable_service.calculate_receivable("43.2", "10", "5") == Decimal("445.00")
    assert receivable_service.calculate_receivable("43", "10", "5") == Decimal("435.00")


def test_billing_weight_rounds_each_package_before_summing(
    client, setup_test_database, salesperson_token
):
    session = setup_test_database
    _, order, _ = _seed_order(session)
    session.add(CargoTable(
        uid="erp-cargo-2",
        target_order_uid=order.uid,
        weight=10.5,
        archive=False,
        create_date="2026-08-27 09:01:00",
    ))
    session.commit()

    assert receivable_service.current_order_weight(session, order.uid) == Decimal("21.000")
    assert receivable_service.current_order_billing_weight(session, order.uid) == Decimal("22.000")
    assert receivable_service.calculate_receivable(
        receivable_service.current_order_billing_weight(session, order.uid),
        "10",
        "5",
    ) == Decimal("225.00")
    response = client.post(
        f"/api/orders/{order.uid}/quotes",
        headers=_headers(salesperson_token),
        json={"unit_price": 10, "surcharge": 5},
    )
    quote = response.get_json()["data"]
    assert quote["weight_snapshot"] == 21.0
    assert quote["billing_weight"] == 22.0
    assert quote["receivable_amount"] == 225.0


def test_fractional_multi_package_order_remains_receivable_after_first_receipt(
    client, setup_test_database, salesperson_token
):
    session = setup_test_database
    customer, order, cargo = _seed_order(session)
    cargo.weight = 0.1
    session.add(CargoTable(
        uid="erp-cargo-2",
        target_order_uid=order.uid,
        weight=0.2,
        archive=False,
        create_date="2026-08-27 09:01:00",
    ))
    session.commit()

    quote = client.post(
        f"/api/orders/{order.uid}/quotes",
        headers=_headers(salesperson_token),
        json={"unit_price": 12.34, "surcharge": 5},
    )
    assert quote.status_code == 200
    assert quote.get_json()["data"]["receivable_amount"] == 29.68

    receipt = client.post(
        "/api/receipts",
        headers=_headers(salesperson_token),
        json={
            "customer_id": customer.id,
            "receipt_date": "2026-08-27",
            "payment_method": "cash",
            "settlement_status": "unsettled",
            "items": [{"order_uid": order.uid, "amount": 10}],
        },
    )
    assert receipt.status_code == 200

    rows = client.get(
        f"/api/receivables/orders?customer_id={customer.id}",
        headers=_headers(salesperson_token),
    ).get_json()["data"]
    assert len(rows) == 1
    assert rows[0]["billing_weight"] == 2.0
    assert rows[0]["receivable_amount"] == 29.68
    assert rows[0]["available_amount"] == 19.68


def test_unfiltered_receivables_list_all_unsettled_orders_for_current_salesperson(
    client, setup_test_database, salesperson_token
):
    session = setup_test_database
    first_customer, first_order, _ = _seed_order(session)
    second_customer = CustomerTable(name="第二客户")
    other_customer = CustomerTable(name="其他业务员客户")
    second_order = OrderTable(
        uid="erp-order-2",
        order_id="ERP-002",
        customer_name=second_customer.name,
        transportation="测试渠道",
        salesman_id=3,
        archive=False,
        create_date="2026-08-27 09:01:00",
    )
    other_salesman = UserTable(
        id=8,
        phone="13800000008",
        name="其他业务员",
        password=hash_password("x"),
        status="approved",
    )
    other_order = OrderTable(
        uid="erp-order-3",
        order_id="ERP-003",
        customer_name=other_customer.name,
        transportation="测试渠道",
        salesman_id=8,
        archive=False,
        create_date="2026-08-27 09:02:00",
    )
    second_order.customers = [second_customer]
    other_order.customers = [other_customer]
    session.add_all([
        second_customer,
        other_customer,
        other_salesman,
        second_order,
        other_order,
        CargoTable(uid="erp-cargo-2", target_order_uid=second_order.uid, weight=5.2, archive=False),
        CargoTable(uid="erp-cargo-3", target_order_uid=other_order.uid, weight=6.2, archive=False),
    ])
    session.commit()

    for order, token in (
        (first_order, salesperson_token),
        (second_order, salesperson_token),
        (other_order, _salesperson_token(8)),
    ):
        assert client.post(
            f"/api/orders/{order.uid}/quotes",
            headers=_headers(token),
            json={"unit_price": 12, "surcharge": 0},
        ).status_code == 200

    response = client.get(
        "/api/receivables/orders?p=1&s=1",
        headers=_headers(salesperson_token),
    )
    assert response.status_code == 200
    page_data = response.get_json()
    assert page_data["total"] == 2
    assert page_data["page"] == 1
    assert page_data["page_size"] == 1
    assert len(page_data["data"]) == 1

    second_page = client.get(
        "/api/receivables/orders?p=2&s=1",
        headers=_headers(salesperson_token),
    ).get_json()
    rows = page_data["data"] + second_page["data"]
    assert {row["order_id"] for row in rows} == {"ERP-001", "ERP-002"}
    assert {row["customer_name"] for row in rows} == {first_customer.name, second_customer.name}

    filtered = client.get(
        f"/api/receivables/orders?customer_id={first_customer.id}",
        headers=_headers(salesperson_token),
    )
    assert [row["order_id"] for row in filtered.get_json()["data"]] == ["ERP-001"]


def test_receivable_filters_use_order_creation_and_quote_owner_before_pagination(
    client, setup_test_database, salesperson_token, admin_token
):
    session = setup_test_database
    customer, first_order, _ = _seed_order(session)
    other_customer = CustomerTable(name="筛选其他客户")
    session.add(other_customer)
    session.flush()
    first_order.create_date = "2026-08-27 00:00:00"
    session.add(OrderQuoteVersionTable(
        order_uid=first_order.uid, version_no=1, quoter_id=3,
        unit_price=12, is_final=True, status="adopted",
        effective_date="2026-09-01 00:00:00",
    ))
    cases = [
        ("end", "2026-08-28 23:59:59", customer, 3),
        ("before", "2026-08-26 23:59:59", customer, 3),
        ("after", "2026-08-29 00:00:00", customer, 3),
        ("owner", "2026-08-28 12:00:00", customer, 7),
        ("customer", "2026-08-28 12:00:00", other_customer, 3),
        ("missing", None, customer, 3),
    ]
    for suffix, created, linked_customer, owner_id in cases:
        order = OrderTable(
            uid=f"filter-{suffix}", order_id=f"FILTER-{suffix}",
            customer_name=linked_customer.name, salesman_id=3,
            archive=False, create_date=created,
        )
        order.customers = [linked_customer]
        session.add_all([
            order,
            CargoTable(uid=f"cargo-{suffix}", target_order_uid=order.uid, weight=1, archive=False),
            OrderQuoteVersionTable(
                order_uid=order.uid, version_no=1, quoter_id=owner_id,
                unit_price=12, is_final=True, status="adopted",
                effective_date="2026-09-01 00:00:00",
            ),
        ])
    session.commit()

    def query(token=admin_token, **filters):
        response = client.get("/api/receivables/orders", headers=_headers(token), query_string=filters)
        assert response.status_code == 200
        return response.get_json()

    filters = dict(customer_id=customer.id, date_from="2026-08-27", date_to="2026-08-28", owner_id=3, s=1)
    first = query(**filters)
    second = query(**filters, p=2)
    assert first["total"] == second["total"] == 2
    assert [row["uid"] for row in first["data"] + second["data"]] == ["filter-end", first_order.uid]
    assert first["data"][0]["create_date"] == "2026-08-28 23:59:59"
    assert second["data"][0]["create_date"] == "2026-08-27 00:00:00"
    assert query(date_from="2026-08-29")["total"] == 1
    assert query(date_to="2026-08-26")["total"] == 1
    assert query()["total"] == 7
    assert query(owner_id=999)["total"] == 0
    assert [row["uid"] for row in query(owner_id=7)["data"]] == ["filter-owner"]
    own = query(token=salesperson_token, owner_id=7)
    assert own["total"] == 6
    assert all(row["quoter_id"] == 3 for row in own["data"])
    assert any(row["create_date"] is None for row in own["data"])


@pytest.mark.parametrize("filters", [
    {"date_from": "2026-02-30"},
    {"date_to": "2026-8-27"},
    {"date_from": "invalid"},
    {"date_to": "2026-08-27 12:00:00"},
    {"date_from": ""},
    {"date_from": "2026-08-29", "date_to": "2026-08-28"},
])
def test_receivable_filters_reject_invalid_dates(client, salesperson_token, filters):
    response = client.get(
        "/api/receivables/orders", headers=_headers(salesperson_token), query_string=filters
    )
    assert response.status_code == 400
    assert response.get_json()["code"] == 400


def test_live_receivable_ignores_legacy_quote_snapshot_mismatch(
    client, setup_test_database, salesperson_token
):
    session = setup_test_database
    customer, order, _ = _seed_order(session)
    assert client.post(
        f"/api/orders/{order.uid}/quotes",
        headers=_headers(salesperson_token),
        json={"unit_price": 12.34, "surcharge": 5},
    ).status_code == 200
    assert client.post(
        "/api/receipts",
        headers=_headers(salesperson_token),
        json={
            "customer_id": customer.id,
            "receipt_date": "2026-08-27",
            "payment_method": "cash",
            "items": [{"order_uid": order.uid, "amount": 10}],
        },
    ).status_code == 200

    quote = session.query(OrderQuoteVersionTable).filter_by(order_uid=order.uid).one()
    quote.receivable_amount = Decimal("134.57")
    session.commit()

    state = receivable_service.get_order_quote_state(order.uid)
    assert state["is_effective"] is True
    assert state["validity_status"] == "effective"
    assert state["receivable_amount"] == 140.74


def test_only_current_order_salesperson_can_quote(
    client, setup_test_database, salesperson_token
):
    session = setup_test_database
    _, order, _ = _seed_order(session)

    response = client.post(
        f"/api/orders/{order.uid}/quotes",
        headers=_headers(_salesperson_token()),
        json={"unit_price": 12.34, "surcharge": 5},
    )

    assert response.status_code == 403
    assert response.get_json()["msg"] == "仅当前订单的业务员可以报价"
    assert session.query(OrderQuoteVersionTable).filter_by(order_uid=order.uid).count() == 0


def test_quote_formula_is_live_until_receipt_then_order_mutations_are_blocked(
    client, setup_test_database, salesperson_token
):
    session = setup_test_database
    customer, order, cargo = _seed_order(session)

    response = client.post(
        f"/api/orders/{order.uid}/quotes",
        headers=_headers(salesperson_token),
        json={"unit_price": 12.34, "surcharge": 5, "quote_remark": "公式报价"},
    )
    assert response.status_code == 200
    quote = response.get_json()["data"]
    assert quote["unit_price"] == 12.34
    assert quote["weight_snapshot"] == 10.5
    assert quote["billing_weight"] == 11.0
    assert quote["receivable_amount"] == 140.74
    assert quote["is_effective"] is True

    cargo.weight = 11.2
    session.commit()
    live_state = receivable_service.get_order_quote_state(order.uid)
    assert live_state["is_effective"] is True
    assert live_state["weight_snapshot"] == 11.2
    assert live_state["billing_weight"] == 12.0
    assert live_state["receivable_amount"] == 153.08

    receipt_response = client.post(
        "/api/receipts",
        headers=_headers(salesperson_token),
        json={
            "customer_id": customer.id,
            "receipt_date": "2026-08-27",
            "payment_method": "cash",
            "items": [{"order_uid": order.uid, "amount": 10}],
        },
    )
    assert receipt_response.status_code == 200
    session.expire_all()
    locked_quote = session.query(OrderQuoteVersionTable).filter_by(order_uid=order.uid).one()
    assert float(locked_quote.weight_snapshot) == 11.2
    assert float(locked_quote.billing_weight_snapshot) == 12.0
    assert float(locked_quote.receivable_amount) == 153.08
    locked_state = receivable_service.get_order_quote_state(order.uid)
    assert locked_state["is_effective"] is True
    order_detail = client.get(
        f"/api/orders/{order.uid}",
        headers=_headers(salesperson_token),
    )
    assert order_detail.get_json()["data"]["receipt_locked"] is True

    blocked = client.put(
        f"/api/cargo/{cargo.uid}",
        headers=_headers(salesperson_token),
        json={"weight": 11.3},
    )
    assert blocked.status_code == 409
    assert blocked.get_json()["msg"] == RECEIPT_LOCKED_MESSAGE


def test_rejected_receipt_permanently_blocks_all_receivable_basis_mutations(
    client, setup_test_database, salesperson_token, admin_token
):
    session = setup_test_database
    customer, order, cargo = _seed_order(session)
    packing_list = PackingListTable(
        uid="packing-1",
        list_number="LOCK-TEST",
        customer_id=customer.id,
        creator_id=1,
        status="completed",
        archive=False,
        create_date="2026-08-27 08:00:00",
    )
    assigned_box = CargoTable(
        uid="packing-box-assigned",
        packing_list_uid=packing_list.uid,
        target_order_uid=order.uid,
        weight=2.4,
        archive=False,
        status=0,
        box_number=1,
        create_date="2026-08-27 08:01:00",
    )
    unassigned_box = CargoTable(
        uid="packing-box-unassigned",
        packing_list_uid=packing_list.uid,
        target_order_uid=None,
        weight=1.2,
        archive=False,
        status=0,
        box_number=2,
        create_date="2026-08-27 08:02:00",
    )
    session.add_all([packing_list, assigned_box, unassigned_box])
    session.commit()
    customer_id = customer.id
    order_uid = order.uid
    cargo_uid = cargo.uid
    assigned_box_uid = assigned_box.uid
    unassigned_box_uid = unassigned_box.uid

    assert client.post(
        f"/api/orders/{order_uid}/quotes",
        headers=_headers(salesperson_token),
        json={"unit_price": 12.34, "surcharge": 5},
    ).status_code == 200
    pending_quote = client.post(
        f"/api/orders/{order_uid}/quotes",
        headers=_headers(salesperson_token),
        json={"unit_price": 10, "surcharge": 0},
    ).get_json()["data"]
    assert pending_quote["status"] == "pending"

    receipt = client.post(
        "/api/receipts",
        headers=_headers(salesperson_token),
        json={
            "customer_id": customer_id,
            "receipt_date": "2026-08-27",
            "payment_method": "cash",
            "items": [{"order_uid": order_uid, "amount": 10}],
        },
    ).get_json()["data"]
    rejected = client.put(
        f"/api/finance/receipts/{receipt['id']}/review",
        headers=_headers(_finance_token()),
        json={"action": "reject", "review_remark": "测试驳回"},
    )
    assert rejected.status_code == 200

    locked_requests = [
        client.post(
            f"/api/orders/{order_uid}/add_cargo",
            headers=_headers(salesperson_token),
            json={"cargo_count": 1},
        ),
        client.put(
            f"/api/cargo/{cargo_uid}",
            headers=_headers(salesperson_token),
            json={"weight": 11.0},
        ),
        client.post(
            "/api/cargo/unbind",
            headers=_headers(salesperson_token),
            json={"cargo_id_list": [cargo_uid]},
        ),
        client.post(
            "/api/cargo/archive",
            headers=_headers(salesperson_token),
            json={"cargo_id_list": [cargo_uid]},
        ),
        client.delete(
            "/api/cargo",
            headers=_headers(salesperson_token),
            json={"cargo_id_list": [cargo_uid]},
        ),
        client.put(
            f"/api/box/{assigned_box_uid}/weigh",
            headers=_headers(salesperson_token),
            json={"weight": 3.0},
        ),
        client.post(
            "/api/boxes/assign",
            headers=_headers(salesperson_token),
            json={"box_uids": [unassigned_box_uid], "order_uid": order_uid},
        ),
        client.post(
            f"/api/orders/{order_uid}/quotes",
            headers=_headers(salesperson_token),
            json={"unit_price": 13, "surcharge": 5},
        ),
        client.put(
            f"/api/finance/quote-approvals/{pending_quote['id']}",
            headers=_headers(admin_token),
            json={"action": "approve", "review_remark": "不应批准"},
        ),
        client.post(
            f"/api/orders/{order_uid}/archive",
            headers=_headers(salesperson_token),
        ),
        client.delete(
            f"/api/orders/{order_uid}",
            headers=_headers(salesperson_token),
        ),
    ]
    for response in locked_requests:
        assert response.status_code == 409
        assert response.get_json()["msg"] == RECEIPT_LOCKED_MESSAGE

    session.expire_all()
    assert session.query(CargoTable).filter_by(uid=unassigned_box_uid).one().target_order_uid is None
    assert session.query(CargoTable).filter_by(uid=cargo_uid).one().archive is False

    allowed = client.put(
        f"/api/cargo/{cargo_uid}",
        headers=_headers(salesperson_token),
        json={"real_en_name": "SHOES", "weight": 10.5},
    )
    assert allowed.status_code == 200
    session.expire_all()
    assert session.query(CargoTable).filter_by(uid=cargo_uid).one().real_en_name == "SHOES"


def test_low_unit_price_requires_review_even_with_large_surcharge(
    client, setup_test_database, salesperson_token, admin_token
):
    session = setup_test_database
    _, order, _ = _seed_order(session)

    response = client.post(
        f"/api/orders/{order.uid}/quotes",
        headers=_headers(salesperson_token),
        json={"unit_price": 10.9999, "surcharge": 500},
    )
    assert response.status_code == 200
    quote = response.get_json()["data"]
    assert quote["status"] == "pending"
    assert quote["is_effective"] is False
    assert quote["receivable_amount"] == 621.0

    approved = client.put(
        f"/api/finance/quote-approvals/{quote['id']}",
        headers=_headers(admin_token),
        json={"action": "approve", "review_remark": "例外批准"},
    )
    assert approved.status_code == 200
    approved_quote = approved.get_json()["data"]
    assert approved_quote["status"] == "approved"
    assert approved_quote["is_effective"] is True
    assert approved_quote["effective_date"]


def test_partial_receipts_reserve_balance_and_finance_approval(
    client, setup_test_database, salesperson_token, admin_token
):
    session = setup_test_database
    customer, order, _ = _seed_order(session)
    quote_response = client.post(
        f"/api/orders/{order.uid}/quotes",
        headers=_headers(salesperson_token),
        json={"unit_price": 12.34, "surcharge": 5},
    )
    assert quote_response.status_code == 200
    quote = session.query(OrderQuoteVersionTable).filter_by(order_uid=order.uid).one()
    quote.effective_date = "2026-08-27 08:00:00"
    session.commit()

    first = client.post(
        "/api/receipts",
        headers=_headers(salesperson_token),
        json={
            "customer_id": customer.id,
            "receipt_date": "2026-08-27",
            "payment_method": "bank_transfer",
            "items": [{"order_uid": order.uid, "amount": 80}],
        },
    )
    assert first.status_code == 200
    receipt = first.get_json()["data"]
    assert receipt["status"] == "pending"
    assert receipt["receipt_no"].startswith("RCPT-20260827-")

    for url in (
        "/api/receivables/orders",
        f"/api/receivables/orders?customer_id={customer.id}",
    ):
        partial_rows = client.get(url, headers=_headers(salesperson_token)).get_json()["data"]
        assert len(partial_rows) == 1
        assert partial_rows[0]["available_amount"] == 60.74

    over_reserved = client.post(
        "/api/receipts",
        headers=_headers(salesperson_token),
        json={
            "customer_id": customer.id,
            "receipt_date": "2026-08-27",
            "payment_method": "cash",
            "items": [{"order_uid": order.uid, "amount": 61}],
        },
    )
    assert over_reserved.status_code == 400
    assert "最多可收 60.74" in over_reserved.get_json()["msg"]

    approved = client.put(
        f"/api/finance/receipts/{receipt['id']}/review",
        headers=_headers(admin_token),
        json={"action": "approve", "review_remark": "到账无误"},
    )
    assert approved.status_code == 200
    assert approved.get_json()["data"]["status"] == "approved"

    eligible = client.get(
        f"/api/receivables/orders?customer_id={customer.id}",
        headers=_headers(salesperson_token),
    )
    assert eligible.status_code == 200
    assert eligible.get_json()["data"][0]["billing_weight"] == 11.0
    assert eligible.get_json()["data"][0]["available_amount"] == 60.74

    second = client.post(
        "/api/receipts",
        headers=_headers(salesperson_token),
        json={
            "customer_id": customer.id,
            "receipt_date": "2026-08-27",
            "payment_method": "wechat",
            "items": [{"order_uid": order.uid, "amount": 60.74}],
        },
    )
    assert second.status_code == 200
    assert second.get_json()["data"]["items"][0]["remaining_after"] == 0.0

    for url in (
        "/api/receivables/orders",
        f"/api/receivables/orders?customer_id={customer.id}",
    ):
        settled_rows = client.get(url, headers=_headers(salesperson_token)).get_json()["data"]
        assert settled_rows == []

    receipt_page = client.get(
        "/api/receipts?p=1&s=1",
        headers=_headers(salesperson_token),
    )
    assert receipt_page.status_code == 200
    receipt_page_data = receipt_page.get_json()
    assert receipt_page_data["total"] == 2
    assert receipt_page_data["page_size"] == 1
    assert len(receipt_page_data["data"]) == 1
    assert "items" not in receipt_page_data["data"][0]
    assert receipt_page_data["data"][0]["total_amount"] > 0

    first_receipt = session.query(PaymentReceiptTable).filter_by(id=receipt["id"]).one()
    second_receipt = session.query(PaymentReceiptTable).filter_by(id=second.get_json()["data"]["id"]).one()
    first_receipt.review_date = "2026-08-27 12:00:00"
    second_receipt.create_date = "2026-08-27 13:00:00"
    session.commit()

    ledger = client.get(
        "/api/finance/accounts-receivable?as_of=2026-08-27",
        headers=_headers(_finance_token()),
    )
    assert ledger.status_code == 200
    totals = ledger.get_json()["data"]["totals"]
    assert totals["receivable_amount"] == 140.74
    assert totals["received_amount"] == 80.0
    assert totals["outstanding_amount"] == 60.74
    assert totals["pending_amount"] == 60.74


def test_receipt_creator_cannot_review_own_admin_receipt(
    client, setup_test_database, salesperson_token, admin_token
):
    session = setup_test_database
    customer, order, _ = _seed_order(session)
    assert client.post(
        f"/api/orders/{order.uid}/quotes",
        headers=_headers(salesperson_token),
        json={"unit_price": 12.34, "surcharge": 5},
    ).status_code == 200

    created = client.post(
        "/api/receipts",
        headers=_headers(admin_token),
        json={
            "customer_id": customer.id,
            "receipt_date": "2026-08-27",
            "payment_method": "cash",
            "items": [{"order_uid": order.uid, "amount": 10}],
        },
    )
    assert created.status_code == 200
    receipt_id = created.get_json()["data"]["id"]

    response = client.put(
        f"/api/finance/receipts/{receipt_id}/review",
        headers=_headers(admin_token),
        json={"action": "approve"},
    )
    assert response.status_code == 403
    assert "不能审核自己" in response.get_json()["msg"]


def test_cross_customer_and_other_salesperson_receipts_are_rejected(
    client, setup_test_database, salesperson_token
):
    session = setup_test_database
    customer, order, _ = _seed_order(session)
    other_customer = CustomerTable(name="其他客户")
    session.add_all([
        other_customer,
        UserTable(
            id=8,
            phone="13800000008",
            name="其他业务员",
            password=hash_password("x"),
            status="approved",
        ),
    ])
    session.commit()
    assert client.post(
        f"/api/orders/{order.uid}/quotes",
        headers=_headers(salesperson_token),
        json={"unit_price": 12.34, "surcharge": 5},
    ).status_code == 200

    common_body = {
        "receipt_date": "2026-08-27",
        "payment_method": "cash",
        "items": [{"order_uid": order.uid, "amount": 10}],
    }
    wrong_customer = client.post(
        "/api/receipts",
        headers=_headers(salesperson_token),
        json={**common_body, "customer_id": other_customer.id},
    )
    assert wrong_customer.status_code == 400
    assert "不属于所选客户" in wrong_customer.get_json()["msg"]

    wrong_owner = client.post(
        "/api/receipts",
        headers=_headers(_salesperson_token()),
        json={**common_body, "customer_id": customer.id},
    )
    assert wrong_owner.status_code == 403
    assert "不属于你的跟单范围" in wrong_owner.get_json()["msg"]


def test_accounts_receivable_reconstructs_pending_state_at_cutoff(
    client, setup_test_database, salesperson_token, admin_token
):
    session = setup_test_database
    customer, order, _ = _seed_order(session)
    assert client.post(
        f"/api/orders/{order.uid}/quotes",
        headers=_headers(salesperson_token),
        json={"unit_price": 12.34, "surcharge": 5},
    ).status_code == 200
    quote = session.query(OrderQuoteVersionTable).filter_by(order_uid=order.uid).one()
    quote.effective_date = "2026-08-27 08:00:00"
    session.commit()
    created = client.post(
        "/api/receipts",
        headers=_headers(salesperson_token),
        json={
            "customer_id": customer.id,
            "receipt_date": "2026-08-27",
            "payment_method": "bank_transfer",
            "items": [{"order_uid": order.uid, "amount": 80}],
        },
    ).get_json()["data"]
    assert client.put(
        f"/api/finance/receipts/{created['id']}/review",
        headers=_headers(admin_token),
        json={"action": "approve"},
    ).status_code == 200

    receipt = session.query(PaymentReceiptTable).filter_by(id=created["id"]).one()
    receipt.create_date = "2026-08-27 09:00:00"
    receipt.review_date = "2026-08-28 09:00:00"
    session.commit()

    before_review = receivable_service.accounts_receivable_ledger("2026-08-27")
    assert before_review["totals"]["received_amount"] == 0.0
    assert before_review["totals"]["pending_amount"] == 80.0
    after_review = receivable_service.accounts_receivable_ledger("2026-08-28")
    assert after_review["totals"]["received_amount"] == 80.0
    assert after_review["totals"]["pending_amount"] == 0.0


def test_accounts_receivable_filters_total_by_quote_effective_date_range(
    client, setup_test_database, salesperson_token
):
    session = setup_test_database
    _, order, _ = _seed_order(session)
    assert client.post(
        f"/api/orders/{order.uid}/quotes",
        headers=_headers(salesperson_token),
        json={"unit_price": 12.34, "surcharge": 5},
    ).status_code == 200

    quote = session.query(OrderQuoteVersionTable).filter_by(order_uid=order.uid).one()
    quote.effective_date = "2026-08-20 10:00:00"
    session.commit()

    included = client.get(
        "/api/finance/accounts-receivable?date_from=2026-08-15&date_to=2026-08-25",
        headers=_headers(_finance_token()),
    )
    assert included.status_code == 200
    included_data = included.get_json()["data"]
    assert included_data["items"][0]["billing_weight"] == 11.0
    assert included_data["totals"]["receivable_amount"] == 140.74
    assert included_data["date_from"] == "2026-08-15"
    assert included_data["date_to"] == "2026-08-25"

    excluded = client.get(
        "/api/finance/accounts-receivable?date_from=2026-08-21&date_to=2026-08-25",
        headers=_headers(_finance_token()),
    )
    assert excluded.status_code == 200
    assert excluded.get_json()["data"]["totals"]["receivable_amount"] == 0.0


def test_followup_bonus_uses_effective_dated_rate_versions(
    client, setup_test_database, salesperson_token
):
    session = setup_test_database
    customer, first_order, _ = _seed_order(session)
    second_order = OrderTable(
        uid="erp-order-2",
        order_id="ERP-002",
        customer_name=customer.name,
        transportation="测试渠道",
        salesman_id=3,
        archive=False,
        create_date="2026-08-20 09:00:00",
    )
    second_order.customers = [customer]
    second_cargo = CargoTable(
        uid="erp-cargo-2",
        target_order_uid=second_order.uid,
        weight=5,
        archive=False,
        create_date="2026-08-20 09:00:00",
    )
    session.add_all([second_order, second_cargo])
    session.commit()
    for order in (first_order, second_order):
        assert client.post(
            f"/api/orders/{order.uid}/quotes",
            headers=_headers(salesperson_token),
            json={"unit_price": 12, "surcharge": 0},
        ).status_code == 200

    quotes = session.query(OrderQuoteVersionTable).order_by(OrderQuoteVersionTable.order_uid).all()
    quotes[0].effective_date = "2026-08-15 09:00:00"
    quotes[1].effective_date = "2026-08-25 09:00:00"
    session.commit()
    finance_payload = {"user_id": 7, "name": "财务测试", "role": "finance"}
    receivable_service.create_sales_bonus_rate(
        {"effective_from": "2026-08-01", "rate_per_kg": 0.5}, finance_payload
    )
    receivable_service.create_sales_bonus_rate(
        {"effective_from": "2026-08-20", "rate_per_kg": 1}, finance_payload
    )

    result = receivable_service.salesperson_followup_bonus(3, "2026-08")
    assert result["order_count"] == 2
    assert result["total_weight"] == 15.5
    assert result["orders"][0]["rate_per_kg"] == 0.5
    assert result["orders"][1]["rate_per_kg"] == 1.0
    assert result["estimated_bonus"] == 10.25
