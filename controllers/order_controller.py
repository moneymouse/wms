import json
import time

from flask import Blueprint, jsonify, request

from Auth import verify, allow, get_token_payload
from data import (
    order_model,
    cargo_model,
    RecordExist,
    add_customer_record,
)
from data.user.User import user_model
from services.order_service import filter_orders, sort_orders
from utils.log import log

order_bp = Blueprint("order", __name__, url_prefix="/api")


# 创建订单
@order_bp.post("/create")
@verify
@log(desc="Create order.", is_json=True)
@allow()
def create_order():
    """创建订单。

    Request body 中的 customer_name 用于：
    1. 查找已存在的客户并关联到订单
    2. 添加收件人信息到该客户名下

    如果 customer_name 对应的客户不存在，返回 404 错误。
    """
    from data.customer.Customer import CustomerTable
    from data.database import SessionFactory

    record = json.loads(request.data)
    customer_name = record.get("customer_name", "").strip()

    # 验证客户是否存在
    customer = None
    if customer_name:
        s = SessionFactory()
        try:
            customer = s.query(CustomerTable).filter_by(name=customer_name).first()
            if customer is None:
                return jsonify({"code": 404, "msg": f"Customer '{customer_name}' not found"}), 404
            customer_id = customer.id
        finally:
            s.close()
    else:
        customer_id = None

    # 添加收件人信息（客户已验证存在）
    add_customer_record(record)

    try:
        record["order_date"] = time.strftime("%Y-%m-%d %H:%M")
        # Set the current user as the default salesman
        payload = get_token_payload()
        if payload and payload.get("user_id"):
            record["salesman_id"] = payload["user_id"]
        order_uid = order_model.create(record)

        # 关联客户
        if customer_id:
            order_model.add_customer(order_uid, customer_id)

    except RecordExist:
        return jsonify({"code": 500, "msg": "Record Existed"})
    return jsonify({"code": 200, "msg": "success"})


# 获取订单列表（支持分页、搜索、排序）
@order_bp.get("/orders")
@verify
@allow()
def get_order_list():
    page = request.args.get("p", 1, type=int) - 1
    page_size = request.args.get("s", 30, type=int)
    sorted_field = request.args.get("sf", "create_date", type=str)
    sorted_order = request.args.get("so", 1, type=int)
    query_param = request.args.get("q", "", type=str)

    order_list = order_model.read()
    order_list = filter_orders(order_list, query_param, cargo_model)
    order_list = sort_orders(order_list, sorted_field, sorted_order)

    start = page * page_size
    end = min(start + page_size, len(order_list))
    return jsonify(
        {"code": 200, "data": order_list[start:end], "total": len(order_list)}
    )


# 获取单个订单
@order_bp.get("/orders/<string:uid>")
@verify
@allow()
def get_order(uid):
    return jsonify({"code": 200, "data": order_model.read(uid)})


# 更新订单
@order_bp.put("/orders/<string:uid>")
@allow()
@verify
@log(desc="Update order.", is_json=True)
def update_order(uid):
    order_model.update(uid, json.loads(request.data))
    return jsonify({"code": 200, "msg": "success"})


# 删除单个订单
@order_bp.delete("/orders/<string:uid>")
@allow()
@verify
@log(desc="Delete order.")
def delete_order(uid):
    order_model.delete(uid)
    return jsonify({"code": 200, "msg": "success"})


# 批量删除订单
@order_bp.delete("/orders")
@verify
@allow()
@log(desc="Delete orders.", is_json=True)
def delete_order_list():
    uid_list = json.loads(request.data)["uid_list"]
    for uid in uid_list:
        order_model.delete(uid)
    return jsonify({"code": 200, "msg": "success"})


# 为订单添加包裹
@order_bp.post("/orders/<string:uid>/add_cargo")
@verify
@allow()
def add_cargo(uid):
    record = json.loads(request.data)
    cargo_delta = record.get("cargo_count", 0)

    if cargo_delta <= 0:
        return jsonify({"code": 404, "msg": "Cargo count should larger than 0"})

    order = order_model.read(uid)
    cargo_count = order["cargo_count"] or 0
    cargo_count_n = cargo_count + cargo_delta
    order_model.update(uid, {"cargo_count": cargo_count_n})

    order_id = order["order_id"]
    cargo_uid_list = order_model.read(uid)["cargo_uid_list"]
    result = []
    for i in range(cargo_count + 1, cargo_count_n + 1):
        cargo_uid = cargo_model.create(
            {
                "origin_id": f"{order_id}-{i}",
                "status": 0,
                "tag": f'{order["tag_all"]}_{i}',
                "target_order_uid": uid,
            }
        )
        cargo_uid_list.append(cargo_uid)
        result.append(cargo_model.read(cargo_uid))

    order_model.update(uid, {"cargo_uid_list": cargo_uid_list})
    return jsonify({"code": 200, "data": result, "cargo_id_list": cargo_uid_list})


# 获取订单负责人
@order_bp.get("/orders/<string:uid>/salesman")
@verify
@allow()
def get_order_salesman(uid):
    salesman = order_model.get_salesman(uid)
    return jsonify({"code": 200, "data": salesman})


# 更新订单负责人
@order_bp.put("/orders/<string:uid>/salesman")
@verify
@log(desc="Update order salesman.", is_json=True)
@allow()
def update_order_salesman(uid):
    """
    Update the salesman for an order.
    Only the current salesman or admin can modify.
    Request body: {"user_id": 1} or {"user_id": null} to remove
    """
    payload = get_token_payload()
    if not payload:
        return jsonify({"code": 401, "msg": "Unauthorized"}), 401

    current_user_id = payload.get("id")
    current_user_role = payload.get("role")

    # Check permission: only admin or current salesman can modify
    is_admin = current_user_role == "admin"
    is_current_salesman = order_model.is_salesman(uid, current_user_id)

    if not is_admin and not is_current_salesman:
        return (
            jsonify(
                {
                    "code": 403,
                    "msg": "Permission denied. Only admin or current salesman can modify.",
                }
            ),
            403,
        )

    data = json.loads(request.data)
    user_id = data.get("user_id")

    # If user_id is None, remove the salesman
    if user_id is None:
        success = order_model.remove_salesman(uid)
        if success:
            return jsonify({"code": 200, "msg": "success", "data": None})
        return jsonify({"code": 404, "msg": "Order not found"}), 404

    # Verify the user exists
    user = user_model.get_by_id(user_id)
    if not user:
        return jsonify({"code": 404, "msg": "User not found"}), 404

    success = order_model.set_salesman(uid, user_id)
    if success:
        return jsonify(
            {"code": 200, "msg": "success", "data": order_model.get_salesman(uid)}
        )
    return jsonify({"code": 404, "msg": "Order not found"}), 404
