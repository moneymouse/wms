from Auth import create_jwt, hash_password
from data.DB import (
    CargoTable,
    ExcelTemplateTable,
    OrderQuoteVersionTable,
    OrderTable,
    PaymentReceiptTable,
    TransportationModeTable,
)
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


def test_quote_formula_and_supplier_export_stale_gate(
    client, setup_test_database, salesperson_token
):
    session = setup_test_database
    _, order, cargo = _seed_order(session)

    response = client.post(
        f"/api/orders/{order.uid}/quotes",
        headers=_headers(salesperson_token),
        json={"unit_price": 12.34, "surcharge": 5, "quote_remark": "公式报价"},
    )
    assert response.status_code == 200
    quote = response.get_json()["data"]
    assert quote["unit_price"] == 12.34
    assert quote["weight_snapshot"] == 10.5
    assert quote["receivable_amount"] == 134.57
    assert quote["is_effective"] is True

    cargo.weight = 11
    session.commit()
    response = client.post(
        "/api/cargo/excel/test_supplier",
        headers=_headers(salesperson_token),
        json={"uid_list": [order.uid], "cargo_list": []},
    )
    assert response.status_code == 409
    payload = response.get_json()
    assert payload["data"]["blocked_orders"][0]["order_id"] == "ERP-001"
    assert payload["data"]["blocked_orders"][0]["reason"] == "stale"

    customer_export = client.post(
        "/api/cargo/excel/kehu",
        headers=_headers(salesperson_token),
        json={"uid_list": [order.uid], "cargo_list": []},
    )
    assert customer_export.status_code == 200


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
    assert quote["receivable_amount"] == 615.5

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

    over_reserved = client.post(
        "/api/receipts",
        headers=_headers(salesperson_token),
        json={
            "customer_id": customer.id,
            "receipt_date": "2026-08-27",
            "payment_method": "cash",
            "items": [{"order_uid": order.uid, "amount": 60}],
        },
    )
    assert over_reserved.status_code == 400
    assert "最多可收 54.57" in over_reserved.get_json()["msg"]

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
    assert eligible.get_json()["data"][0]["available_amount"] == 54.57

    second = client.post(
        "/api/receipts",
        headers=_headers(salesperson_token),
        json={
            "customer_id": customer.id,
            "receipt_date": "2026-08-27",
            "payment_method": "wechat",
            "items": [{"order_uid": order.uid, "amount": 54.57}],
        },
    )
    assert second.status_code == 200
    assert second.get_json()["data"]["items"][0]["remaining_after"] == 0.0

    ledger = client.get(
        "/api/finance/accounts-receivable?as_of=2026-08-27",
        headers=_headers(_finance_token()),
    )
    assert ledger.status_code == 200
    totals = ledger.get_json()["data"]["totals"]
    assert totals["receivable_amount"] == 134.57
    assert totals["received_amount"] == 80.0
    assert totals["outstanding_amount"] == 54.57
    assert totals["pending_amount"] == 54.57


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
