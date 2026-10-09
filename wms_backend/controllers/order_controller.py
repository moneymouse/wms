import base64
import json
import time

from flask import Blueprint, current_app, jsonify, request, send_file
from Auth import verify, allow, get_payload_roles, get_token_payload
from data import order_model
from data.database import SessionFactory
from data.DB import (
    OrderQuoteVersionTable,
    OrderTable,
    lock_order_for_update,
)
from data.user.User import user_model
from utils.audit import record_audit
from utils.log import log
from utils.quote_pdf import build_quote_pdf
from utils.shipping_confirmation_pdf import build_shipping_confirmation_pdf
from services import receivable_service, order_service
from services.number_generation_service import (
    GENERATION_ROLES,
    NumberGenerationError,
    generate_order_number,
    generation_options,
)
from services.cargo_service import add_cargos_to_order
from services.order_edit_policy import OrderEditConflictError
from services.address_recognition import AddressRecognitionError, parse_address
from services.shipping_confirmation_service import (
    ShippingConfirmationError,
    load_shipping_confirmation_details,
)
from data.order_version import (
    get_version_detail,
    list_historical_orders,
    list_versions,
)

order_bp = Blueprint("order", __name__, url_prefix="/api")

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
    """创建订单；共享业务保持现有分阶段提交与响应契约。"""
    try:
        result = order_service.create_order(
            json.loads(request.data), get_token_payload() or {}
        )
        return jsonify(result)
    except order_service.BusinessError as exc:
        return jsonify(exc.to_dict()), exc.http_status


# 获取订单列表（支持分页、搜索、排序）
@order_bp.get("/orders")
@verify
@allow(role=["admin", "store_manager", "salesperson", "clerk"])
def get_order_list():
    return jsonify(order_service.list_orders(
        p=request.args.get("p", 1, type=int),
        s=request.args.get("s", 30, type=int),
        sf=request.args.get("sf", "create_date", type=str),
        so=request.args.get("so", 1, type=int),
        q=request.args.get("q", "", type=str),
    ))


# 获取单个订单
@order_bp.get("/orders/<string:uid>")
@verify
@allow()
def get_order(uid):
    return jsonify(order_service.get_order(uid, get_token_payload() or {}))


@order_bp.get("/orders/<string:uid>/customer-contact")
@verify
@allow(role=["admin", "store_manager", "salesperson"])
def get_order_customer_contact(uid):
    payload = get_token_payload() or {}
    try:
        result = order_service.get_order_customer_contact(uid, payload)
    except order_service.BusinessError as exc:
        return jsonify(exc.to_dict()), exc.http_status

    from services.customer_access import current_user_id
    from utils.audit_log import log_sensitive_access, ACTION_VIEW_SINGLE

    customer = result["data"]
    log_sensitive_access(
        user_id=current_user_id(payload),
        user_role=get_payload_roles(payload),
        user_name=payload.get("name"),
        action=ACTION_VIEW_SINGLE,
        customer_name=customer["name"] if customer else f"Order:{uid}",
        ip_address=request.remote_addr,
    )
    response = jsonify(result)
    response.headers["Cache-Control"] = "private, no-store"
    return response


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


@order_bp.post("/orders/<string:uid>/generate-order-number")
@verify
@allow(role=GENERATION_ROLES)
@log(desc="Generate order number.", is_json=True)
def generate_order_number_route(uid):
    try:
        options = generation_options(request.get_json(silent=True) if request.data else {})
        result = generate_order_number(uid, get_token_payload() or {}, **options)
        return jsonify({"code": 200, "msg": "订单号已生成", "data": result})
    except NumberGenerationError as exc:
        return jsonify({"code": exc.code, "msg": str(exc)}), exc.code
    except OrderEditConflictError as exc:
        return jsonify({"code": 409, "msg": str(exc)}), 409


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
        session.flush()
        after_data = _quote_dict(session, quote)
        if action == "approve":
            after_data["order_transportation"] = quote.transportation_name

        record_audit(
            event_type="order_quote", target_type="quote", target_id=quote_id,
            action=f"quote_{action}", before_data=before_data,
            after_data=after_data, remark=review_remark, session=session,
            operator_payload=get_token_payload() or {},
            metadata={"order_uid": quote.order_uid},
        )
        session.commit()
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


@order_bp.post("/orders/shipping-confirmation/pdf")
@verify
@allow()
def export_shipping_confirmation_pdf():
    """Export selected orders or boxes as compact printable confirmation cards."""
    try:
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            raise ShippingConfirmationError("请求须为 JSON 对象")
        details = load_shipping_confirmation_details(
            data.get("uid_list"), data.get("cargo_list")
        )
        stream = build_shipping_confirmation_pdf(details)
    except ShippingConfirmationError as exc:
        return jsonify({"code": exc.status, "msg": str(exc)}), exc.status
    except ValueError as exc:
        return jsonify({"code": 400, "msg": str(exc)}), 400
    except Exception:
        current_app.logger.exception("Shipping confirmation PDF export failed")
        return jsonify({"code": 500, "msg": "出货确认单生成失败，请稍后重试"}), 500

    response = send_file(
        stream,
        mimetype="application/pdf",
        as_attachment=True,
        download_name="shipping-confirmation.pdf",
        max_age=0,
    )
    response.headers["Cache-Control"] = "private, no-store"
    return response
