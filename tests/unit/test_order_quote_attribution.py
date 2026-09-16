"""创建订单时的首版报价测试。"""

from data.database import SessionFactory
from data.DB import OrderQuoteVersionTable, OrderTable
from data.user.User import UserTable


def _create_salesman():
    session = SessionFactory()
    try:
        session.add(UserTable(
            id=3,
            phone="13800000003",
            name="业务员测试",
            password="test-password",
            status="approved",
            create_date="2023-01-01 10:00",
        ))
        session.commit()
    finally:
        session.close()


def test_create_order_generates_quote_for_selected_salesman(client, clerk_token):
    """创建人可提交报价草稿，首版报价归属所选业务员。"""
    _create_salesman()

    response = client.post(
        "/api/create",
        headers={"x-token": clerk_token},
        json={
            "order_id": "ORDER-WITH-QUOTE",
            "salesman_id": 3,
            "transportation": "未维护渠道",
            "quote": {
                "unit_price": 12.5,
                "surcharge": 8,
                "quote_remark": "创建订单时报价",
            },
        },
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data["code"] == 200
    assert data["msg"] == "创建成功并已生成报价"
    assert data["data"]["quote"]["version_no"] == 1
    assert data["data"]["quote"]["quoter_id"] == 3
    assert data["data"]["quote"]["quoter_name"] == "业务员测试"

    session = SessionFactory()
    try:
        order = session.query(OrderTable).filter_by(uid=data["uid"]).one()
        quote = session.query(OrderQuoteVersionTable).filter_by(order_uid=data["uid"]).one()
        assert order.salesman_id == 3
        assert quote.quoter_id == order.salesman_id
        assert float(quote.unit_price) == 12.5
        assert float(quote.surcharge) == 8
    finally:
        session.close()


def test_invalid_create_quote_does_not_create_order(client, clerk_token):
    """报价字段校验应发生在订单写入之前。"""
    _create_salesman()

    response = client.post(
        "/api/create",
        headers={"x-token": clerk_token},
        json={
            "order_id": "ORDER-INVALID-QUOTE",
            "salesman_id": 3,
            "quote": {"surcharge": 8},
        },
    )

    assert response.status_code == 400
    session = SessionFactory()
    try:
        assert session.query(OrderTable).filter_by(order_id="ORDER-INVALID-QUOTE").first() is None
    finally:
        session.close()


def test_regular_quote_endpoint_still_requires_current_salesman(
    client, salesperson_token, clerk_token
):
    """服务复用不应放宽订单详情报价接口的原权限。"""
    session = SessionFactory()
    try:
        session.add(OrderTable(
            uid="regular-quote-order",
            order_id="ORDER-REGULAR-QUOTE",
            transportation="未维护渠道",
            salesman_id=3,
            archive=False,
            create_date="2023-01-01 10:00",
        ))
        session.commit()
    finally:
        session.close()

    denied = client.post(
        "/api/orders/regular-quote-order/quotes",
        headers={"x-token": clerk_token},
        json={"unit_price": 12.5, "surcharge": 0},
    )
    assert denied.status_code == 403

    accepted = client.post(
        "/api/orders/regular-quote-order/quotes",
        headers={"x-token": salesperson_token},
        json={"unit_price": 12.5, "surcharge": 0},
    )
    assert accepted.status_code == 200
    assert accepted.get_json()["data"]["quoter_id"] == 3
