"""订单列表搜索测试。"""

from data.DB import OrderTable
from data.user.User import UserTable


def test_order_list_searches_by_salesman_name(
    client, setup_test_database, salesperson_token
):
    session = setup_test_database
    matched_salesman = UserTable(
        id=21,
        phone="13800000021",
        name="张三业务员",
        password="test-password",
        status="approved",
    )
    other_salesman = UserTable(
        id=22,
        phone="13800000022",
        name="李四业务员",
        password="test-password",
        status="approved",
    )
    session.add_all([
        matched_salesman,
        other_salesman,
        OrderTable(
            uid="salesman-search-match",
            order_id="ORDER-ZHANG",
            salesman_id=matched_salesman.id,
            archive=False,
        ),
        OrderTable(
            uid="salesman-search-other",
            order_id="ORDER-LI",
            salesman_id=other_salesman.id,
            archive=False,
        ),
    ])
    session.commit()

    response = client.get(
        "/api/orders",
        headers={"x-token": salesperson_token},
        query_string={"q": "张三", "p": 1, "s": 20},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["total"] == 1
    assert [row["order_id"] for row in payload["data"]] == ["ORDER-ZHANG"]
