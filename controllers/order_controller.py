import base64
import json
import time

from flask import Blueprint, jsonify, request
from sqlalchemy import func, or_

from Auth import verify, allow, get_payload_roles, get_token_payload
from data import (
    order_model,
    cargo_model,
    RecordExist,
    add_customer_record,
)
from data.database import SessionFactory
from data.DB import (
    CargoTable,
    OrderQuoteVersionTable,
    OrderTable,
    lock_order_for_update,
)
from data.user.User import UserTable, user_model
from utils.audit import record_audit
from utils.log import log
from utils.quote_pdf import build_quote_pdf
from services import receivable_service
from services.cargo_service import add_cargos_to_order
from services.order_edit_policy import OrderEditConflictError, build_edit_policy
from services.address_recognition import AddressRecognitionError, parse_address
from data.order_version import (
    current_version_no,
    get_version_detail,
    list_historical_orders,
    list_versions,
)

order_bp = Blueprint("order", __name__, url_prefix="/api")

ORDER_LIST_EXCLUDED_FIELDS = {
    "archive",
    "salesman_id",
    "cargo_count",
    "create_date",
}

ORDER_SEARCH_FIELDS = [
    "uid",
    "order_id",
    "customer_name",
    "transportation",
    "receiver",
    "receiver_phone",
    "mail",
    "country",
    "province",
    "city",
    "address",
    "en_name",
    "cn_name",
    "post_code",
    "zip_code",
    "order_date",
    "update_date",
    "tag_all",
]

ORDER_UPDATE_FIELDS = {
    "order_id",
    "transportation",
    "receiver",
    "receiver_phone",
    "mail",
    "country",
    "province",
    "city",
    "address",
    "en_name",
    "cn_name",
    "total_weight",
    "post_code",
    "zip_code",
    "order_date",
    "tag_all",
}


def _serialize_order_list_row(order):
    return {
        col.name: getattr(order, col.name)
        for col in OrderTable.__table__.columns
        if col.name not in ORDER_LIST_EXCLUDED_FIELDS
    }


def _apply_order_search(query, query_param):
    if not query_param:
        return query

    primary = str(query_param).split("-", 1)[0].strip()
    keywords = [k.strip() for k in str(query_param).splitlines() if k.strip()]
    conditions = []
    if primary:
        like = f"%{primary}%"
        conditions.extend(
            getattr(OrderTable, field).ilike(like) for field in ORDER_SEARCH_FIELDS
        )
        conditions.append(OrderTable.salesman.has(UserTable.name.ilike(like)))
    for keyword in keywords:
        like = f"%{keyword}%"
        conditions.append(
            OrderTable.cargos.any(
                or_(
                    CargoTable.transfer_id.ilike(like),
                    CargoTable.waybill_id.ilike(like),
                )
            )
        )
    return query.filter(or_(*conditions)) if conditions else query


def _apply_order_sort(query, sorted_field, sorted_order):
    column = getattr(OrderTable, sorted_field, None)
    if column is None:
        column = OrderTable.create_date
    return query.order_by(column.desc() if sorted_order == 1 else column.asc())


def _current_operator():
    payload = get_token_payload() or {}
    return {
        "id": payload.get("user_id") or payload.get("id"),
        "name": payload.get("name") or payload.get("username") or payload.get("phone"),
        "payload": payload,
    }


def _quote_dict(session, row):
    return receivable_service.quote_to_dict(session, row)


def _order_pdf_dict(order):
    return {
        "uid": order.uid,
        "order_id": order.order_id,
        "customer_name": order.customer_name,
        "receiver": order.receiver,
        "country": order.country,
        "city": order.city,
        "address": order.address,
        "transportation": order.transportation,
    }


@order_bp.post("/orders/parse-address")
@verify
def parse_order_address():
    """Parse a draft address without order writes or raw-address audit logs."""
    try:
        if request.content_length and request.content_length > 32 * 1024:
            raise AddressRecognitionError("请求过大，地址最多可输入 4000 个字符", 413)
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            raise AddressRecognitionError("请求须为 JSON 对象")
        result = parse_address(data.get("address"))
        response = jsonify({"code": 200, "data": result})
    except AddressRecognitionError as exc:
        response = jsonify({"code": exc.status, "msg": str(exc)})
        response.status_code = exc.status
    except Exception:
        from flask import current_app
        current_app.logger.error("Address recognition request failed")
        response = jsonify({"code": 500, "msg": "地址解析暂时失败，请稍后重试或手动填写"})
        response.status_code = 500
    response.headers["Cache-Control"] = "private, no-store"
    return response


# 创建订单
@order_bp.post("/create")
@verify
@log(desc="Create order.", is_json=True)
@allow()
def create_order():
    """创建订单。

    Request body 中优先使用 customer_id 关联客户；customer_name 仅作为兼容兜底和订单快照。

    如果 customer_id / customer_name 对应的客户不存在，返回 404 错误。
    """
    from data.customer.Customer import CustomerTable
    from data.database import SessionFactory

    record = json.loads(request.data)
    quote_payload = record.pop("quote", None)
    if quote_payload is not None:
        try:
            receivable_service.normalize_quote_payload(quote_payload)
        except ValueError as exc:
            return jsonify({"code": 400, "msg": str(exc)}), 400

    payload = get_token_payload() or {}
    raw_salesman_id = record.get("salesman_id")
    if raw_salesman_id not in [None, "", 0, "0"]:
        try:
            salesman_id = int(raw_salesman_id)
        except (TypeError, ValueError):
            return jsonify({"code": 400, "msg": "Invalid salesman_id"}), 400
        if not user_model.get_by_id(salesman_id):
            return jsonify({"code": 404, "msg": "Salesman not found"}), 404
        record["salesman_id"] = salesman_id
    else:
        salesman_id = payload.get("user_id") or payload.get("id")
        if salesman_id is not None:
            record["salesman_id"] = salesman_id

    if quote_payload is not None and salesman_id is None:
        return jsonify({"code": 400, "msg": "提供报价时必须指定业务员"}), 400

    customer_name = str(record.get("customer_name", "") or "").strip()
    raw_customer_id = record.get("customer_id")
    customer_id = None
    if raw_customer_id not in [None, "", 0, "0"]:
        try:
            customer_id = int(raw_customer_id)
        except (TypeError, ValueError):
            return jsonify({"code": 400, "msg": "Invalid customer_id"}), 400

    # 验证客户是否存在
    customer = None
    if customer_id or customer_name:
        s = SessionFactory()
        try:
            if customer_id:
                customer = s.query(CustomerTable).filter_by(id=customer_id).first()
            else:
                customer = s.query(CustomerTable).filter_by(name=customer_name).first()
            if customer is None:
                target = f"ID:{customer_id}" if customer_id else customer_name
                return (
                    jsonify(
                        {"code": 404, "msg": f"Customer '{target}' not found"}
                    ),
                    404,
                )
            customer_id = customer.id
            record["customer_id"] = customer_id
            record["customer_name"] = customer.name
        finally:
            s.close()

    # 添加收件人信息（客户已验证存在）
    add_customer_record(record)

    try:
        record["order_date"] = time.strftime("%Y-%m-%d %H:%M")
        order_uid = order_model.create(record)

    except RecordExist:
        return jsonify({"code": 500, "msg": "Record Existed"})

    quote_result = None
    if quote_payload is not None:
        try:
            quote_result = receivable_service.create_order_quote(
                order_uid=order_uid,
                body=quote_payload,
                operator_payload=payload,
                allow_on_behalf=True,
            )
        except (ValueError, LookupError, PermissionError) as exc:
            return jsonify({
                "code": 500,
                "msg": f"订单已创建，但报价生成失败：{exc}",
                "uid": order_uid,
            }), 500
        record_audit(
            event_type="order_quote",
            target_type="order",
            target_id=order_uid,
            action="quote_submit" if quote_result["status"] == "pending" else "quote_adopt",
            after_data=quote_result,
            remark=quote_result.get("quote_remark"),
        )

    response_data = {
        "code": 200,
        "msg": "创建成功并已生成报价" if quote_result else "success",
        "uid": order_uid,
    }
    if quote_result:
        response_data["data"] = {"quote": quote_result}
    return jsonify(response_data)


# 获取订单列表（支持分页、搜索、排序）
@order_bp.get("/orders")
@verify
@allow(role=["admin", "store_manager", "salesperson", "clerk"])
def get_order_list():
    page = request.args.get("p", 1, type=int) - 1
    page_size = request.args.get("s", 30, type=int)
    sorted_field = request.args.get("sf", "create_date", type=str)
    sorted_order = request.args.get("so", 1, type=int)
    query_param = request.args.get("q", "", type=str)

    page = max(page, 0)
    page_size = min(max(page_size, 1), 200)

    with SessionFactory() as session:
        query = session.query(OrderTable).filter(OrderTable.archive == False)  # noqa: E712
        query = _apply_order_search(query, query_param)
        total = query.count()
        rows = (
            _apply_order_sort(query, sorted_field, sorted_order)
            .offset(page * page_size)
            .limit(page_size)
            .all()
        )
        return jsonify({
            "code": 200,
            "data": [_serialize_order_list_row(row) for row in rows],
            "total": total,
        })


# 获取单个订单
@order_bp.get("/orders/<string:uid>")
@verify
@allow()
def get_order(uid):
    data = order_model.read(uid)
    if data is not None:
        with SessionFactory() as session:
            payload = get_token_payload() or {}
            try:
                policy = build_edit_policy(
                    session,
                    uid,
                    get_payload_roles(payload),
                    payload.get("user_id") or payload.get("id"),
                )
                data.update(policy)
                data["current_version"] = current_version_no(session, uid)
            except LookupError:
                # Compatibility for legacy/model-mocked callers. A real persisted
                # order always resolves through the policy query above.
                pass
    return jsonify({"code": 200, "data": data})


@order_bp.get("/orders/<string:uid>/versions")
@verify
@allow(role=["admin", "store_manager"])
def get_order_versions(uid):
    page = request.args.get("p", 1, type=int)
    page_size = request.args.get("s", 20, type=int)
    return jsonify({"code": 200, "data": list_versions(uid, page, page_size)})


@order_bp.get("/orders/<string:uid>/versions/<int:version_no>")
@verify
@allow(role=["admin", "store_manager"])
def get_order_version(uid, version_no):
    result = get_version_detail(uid, version_no)
    if result is None:
        return jsonify({"code": 404, "msg": "订单版本不存在"}), 404
    return jsonify({"code": 200, "data": result})


@order_bp.get("/order-history")
@verify
@allow(role=["admin", "store_manager"])
def get_order_history():
    deleted_only = request.args.get("deleted_only", "1").lower() not in {
        "0",
        "false",
        "no",
    }
    result = list_historical_orders(
        deleted_only=deleted_only,
        query_text=request.args.get("q", "", type=str),
        page=request.args.get("p", 1, type=int),
        page_size=request.args.get("s", 20, type=int),
    )
    return jsonify({"code": 200, "data": result})


@order_bp.put("/orders/<string:uid>")
@allow()
@verify
@log(desc="Update order.", is_json=True)
def update_order(uid):
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return jsonify({"code": 400, "msg": "订单字段格式不正确"}), 400
    record = {key: value for key, value in body.items() if key in ORDER_UPDATE_FIELDS}
    try:
        order_model.update(uid, record)
    except OrderEditConflictError as exc:
        return jsonify({"code": 409, "msg": str(exc)}), 409
    return jsonify({"code": 200, "msg": "success"})


@order_bp.post("/orders/<string:uid>/archive")
@allow()
@verify
@log(desc="Archive order.")
def archive_order(uid):
    try:
        order_model.archive(uid)
    except OrderEditConflictError as exc:
        return jsonify({"code": 409, "msg": str(exc)}), 409
    return jsonify({"code": 200, "msg": "success"})


# 批量归档订单
@order_bp.post("/orders/archive")
@verify
@allow()
@log(desc="Archive orders.", is_json=True)
def archive_order_list():
    uid_list = json.loads(request.data)["uid_list"]
    try:
        order_model.archive_many(uid_list)
    except OrderEditConflictError as exc:
        return jsonify({"code": 409, "msg": str(exc)}), 409
    return jsonify({"code": 200, "msg": "success"})


# 删除单个订单
@order_bp.delete("/orders/<string:uid>")
@allow()
@verify
@log(desc="Delete order.")
def delete_order(uid):
    try:
        order_model.delete(uid)
    except OrderEditConflictError as exc:
        return jsonify({"code": 409, "msg": str(exc)}), 409
    return jsonify({"code": 200, "msg": "success"})


# 批量删除订单
@order_bp.delete("/orders")
@verify
@allow()
@log(desc="Delete orders.", is_json=True)
def delete_order_list():
    uid_list = json.loads(request.data)["uid_list"]
    try:
        order_model.delete_many(uid_list)
    except OrderEditConflictError as exc:
        return jsonify({"code": 409, "msg": str(exc)}), 409
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

    try:
        result = add_cargos_to_order(uid, cargo_delta)
    except OrderEditConflictError as exc:
        return jsonify({"code": 409, "msg": str(exc)}), 409
    except LookupError as exc:
        return jsonify({"code": 404, "msg": str(exc)}), 404
    return jsonify({"code": 200, **result})


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

    current_user_id = payload.get("user_id") or payload.get("id")
    current_user_roles = set(get_payload_roles(payload))

    # Check permission: only admin or current salesman can modify
    is_admin = "admin" in current_user_roles
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
        try:
            success = order_model.remove_salesman(uid)
        except OrderEditConflictError as exc:
            return jsonify({"code": 409, "msg": str(exc)}), 409
        if success:
            return jsonify({"code": 200, "msg": "success", "data": None})
        return jsonify({"code": 404, "msg": "Order not found"}), 404

    # Verify the user exists
    user = user_model.get_by_id(user_id)
    if not user:
        return jsonify({"code": 404, "msg": "User not found"}), 404

    try:
        success = order_model.set_salesman(uid, user_id)
    except OrderEditConflictError as exc:
        return jsonify({"code": 409, "msg": str(exc)}), 409
    if success:
        return jsonify(
            {"code": 200, "msg": "success", "data": order_model.get_salesman(uid)}
        )
    return jsonify({"code": 404, "msg": "Order not found"}), 404


@order_bp.get("/orders/<string:uid>/quotes")
@verify
@allow(role=["admin", "store_manager", "salesperson", "finance"])
def get_order_quotes(uid):
    with SessionFactory() as session:
        order = (
            session.query(OrderTable)
            .filter(
                OrderTable.uid == uid,
                OrderTable.archive == False,  # noqa: E712
            )
            .first()
        )
        if order is None:
            return jsonify({"code": 404, "msg": "订单不存在"}), 404
        rows = (
            session.query(OrderQuoteVersionTable)
            .filter(
                OrderQuoteVersionTable.order_uid == uid,
                OrderQuoteVersionTable.archive == False,  # noqa: E712
            )
            .order_by(OrderQuoteVersionTable.version_no.desc())
            .all()
        )
        return jsonify({"code": 200, "data": [_quote_dict(session, row) for row in rows]})


@order_bp.post("/orders/<string:uid>/quotes")
@verify
@allow(role=["salesperson"])
def create_order_quote(uid):
    body = json.loads(request.data or "{}")
    try:
        after_data = receivable_service.create_order_quote(
            order_uid=uid,
            body=body,
            operator_payload=get_token_payload() or {},
        )
    except receivable_service.QuoteConflictError as exc:
        return jsonify({"code": 409, "msg": str(exc)}), 409
    except PermissionError as exc:
        return jsonify({"code": 403, "msg": str(exc)}), 403
    except LookupError as exc:
        return jsonify({"code": 404, "msg": str(exc)}), 404
    except ValueError as exc:
        return jsonify({"code": 400, "msg": str(exc)}), 400

    record_audit(
        event_type="order_quote",
        target_type="order",
        target_id=uid,
        action="quote_submit" if after_data["status"] == "pending" else "quote_adopt",
        after_data=after_data,
        remark=after_data.get("quote_remark"),
    )
    msg = "报价已采纳" if after_data["status"] == "adopted" else "报价低于最低限制，已提交管理员审核"
    return jsonify({"code": 200, "msg": msg, "data": after_data})


@order_bp.get("/finance/quote-approvals")
@verify
@allow(role=["admin"])
def get_quote_approvals():
    with SessionFactory() as session:
        rows = (
            session.query(OrderQuoteVersionTable, OrderTable)
            .join(OrderTable, OrderQuoteVersionTable.order_uid == OrderTable.uid)
            .filter(
                OrderTable.archive == False,  # noqa: E712
                OrderQuoteVersionTable.archive == False,  # noqa: E712
                OrderQuoteVersionTable.status == "pending",
            )
            .order_by(OrderQuoteVersionTable.create_date.desc())
            .all()
        )
        data = []
        for quote, order in rows:
            item = _quote_dict(session, quote)
            item.update({
                "order_id": order.order_id,
                "customer_name": order.customer_name,
                "order_transportation": order.transportation,
            })
            data.append(item)
        return jsonify({"code": 200, "data": data})


@order_bp.put("/finance/quote-approvals/<int:quote_id>")
@verify
@allow(role=["admin"])
def review_quote_approval(quote_id):
    body = json.loads(request.data or "{}")
    action = body.get("action")
    review_remark = body.get("review_remark")
    if action not in {"approve", "reject"}:
        return jsonify({"code": 400, "msg": "action 必须是 approve 或 reject"}), 400

    operator = _current_operator()
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    with SessionFactory() as session:
        quote = (
            session.query(OrderQuoteVersionTable)
            .join(OrderTable, OrderTable.uid == OrderQuoteVersionTable.order_uid)
            .filter(
                OrderQuoteVersionTable.id == quote_id,
                OrderQuoteVersionTable.archive == False,  # noqa: E712
                OrderTable.archive == False,  # noqa: E712
            )
            .first()
        )
        if quote is None:
            return jsonify({"code": 404, "msg": "报价记录不存在"}), 404
        if quote.status != "pending":
            return jsonify({"code": 409, "msg": "该报价已审核"}), 409

        before_data = _quote_dict(session, quote)
        order_before = None
        if action == "approve":
            lock_order_for_update(session, quote.order_uid)
            quote = (
                session.query(OrderQuoteVersionTable)
                .filter(
                    OrderQuoteVersionTable.id == quote_id,
                    OrderQuoteVersionTable.archive == False,  # noqa: E712
                )
                .populate_existing()
                .with_for_update()
                .first()
            )
            if quote is None:
                return jsonify({"code": 404, "msg": "报价记录不存在"}), 404
            if quote.status != "pending":
                return jsonify({"code": 409, "msg": "该报价已审核"}), 409
            from data.order_version import record_mutation, snapshot_order

            order_before = snapshot_order(session, quote.order_uid)
            previous_quote = receivable_service.get_current_quote(
                session, quote.order_uid, for_update=True
            )
            previous_receivable = (
                receivable_service.quote_pricing_state(
                    session, previous_quote
                )["receivable_amount"]
                if previous_quote is not None
                else None
            )
            approved_pricing = receivable_service.quote_pricing_state(session, quote)
            (
                session.query(OrderQuoteVersionTable)
                .filter(OrderQuoteVersionTable.order_uid == quote.order_uid)
                .update({"is_final": False})
            )
            quote.status = "approved"
            quote.is_final = True
            quote.effective_date = now
            quote.weight_snapshot = approved_pricing["weight_snapshot"]
            quote.billing_weight_snapshot = approved_pricing["billing_weight"]
            quote.receivable_amount = approved_pricing["receivable_amount"]
            order = (
                session.query(OrderTable)
                .filter(OrderTable.uid == quote.order_uid)
                .first()
            )
            if order is not None:
                order.transportation = quote.transportation_name
                order.update_date = now
        else:
            quote.status = "rejected"
            quote.is_final = False
            quote.effective_date = None
        quote.review_remark = review_remark
        quote.reviewer_id = operator["id"]
        quote.reviewer_name = operator["name"]
        quote.review_date = now
        if action == "approve":
            session.flush()
            receivable_service._create_price_adjustment(
                session,
                order_uid=quote.order_uid,
                previous_quote=previous_quote,
                previous_receivable=previous_receivable,
                new_quote=quote,
                new_receivable=quote.receivable_amount,
                creator=operator,
                now=now,
            )
            record_mutation(
                session,
                quote.order_uid,
                before=order_before,
                after=snapshot_order(session, quote.order_uid),
                action="order_transportation_updated",
                summary="报价审核更新订单运输方式",
                operator_payload=get_token_payload() or {},
            )
        session.commit()
        session.refresh(quote)
        after_data = _quote_dict(session, quote)
        if action == "approve":
            after_data["order_transportation"] = quote.transportation_name

    record_audit(
        event_type="order_quote",
        target_type="quote",
        target_id=quote_id,
        action=f"quote_{action}",
        before_data=before_data,
        after_data=after_data,
        remark=review_remark,
    )
    return jsonify({"code": 200, "msg": "审核完成", "data": after_data})


@order_bp.get("/orders/<string:uid>/quote-pdf")
@verify
@allow(role=["admin", "store_manager", "salesperson", "finance"])
def get_order_quote_pdf(uid):
    with SessionFactory() as session:
        order = session.query(OrderTable).filter(OrderTable.uid == uid).first()
        if order is None:
            return jsonify({"code": 404, "msg": "订单不存在"}), 404

        quote = (
            session.query(OrderQuoteVersionTable)
            .filter(
                OrderQuoteVersionTable.order_uid == uid,
                OrderQuoteVersionTable.archive == False,  # noqa: E712
                OrderQuoteVersionTable.is_final == True,  # noqa: E712
            )
            .order_by(OrderQuoteVersionTable.version_no.desc())
            .first()
        )
        if quote is None:
            return jsonify({"code": 404, "msg": "暂无最终采纳报价"}), 404

        pdf_stream = build_quote_pdf(_order_pdf_dict(order), _quote_dict(session, quote))
        encoded = base64.b64encode(pdf_stream.getvalue()).decode("ascii")
        safe_order_id = order.order_id or uid
        return jsonify({
            "code": 200,
            "filename": f"quote-{safe_order_id}.pdf",
            "mime_type": "application/pdf",
            "data": encoded,
        })
