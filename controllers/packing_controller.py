"""
Packing List Controller - 装箱单和箱子 API 接口

提供装箱单和箱子的 CRUD 操作、照片上传、箱子分配等功能。
"""

import json

from flask import Blueprint, jsonify, request, send_file

from Auth import verify, allow, get_token_payload
from services import packing_list_service
from utils.packing_list_pdf import build_packing_list_pdf
from utils.log import log

packing_bp = Blueprint("packing", __name__, url_prefix="/api")

# 允许创建装箱单的角色
PACKING_CREATE_ROLES = ["admin", "store_manager", "salesperson", "worker"]
# 允许编辑装箱单/箱子详情的角色
PACKING_EDIT_ROLES = ["admin", "store_manager", "salesperson"]
# 允许分配箱子的角色
BOX_ASSIGN_ROLES = ["admin", "store_manager", "salesperson", "clerk"]
# 允许出货的角色
BOX_SHIP_ROLES = ["admin", "store_manager", "salesperson", "clerk", "worker"]


# ---------------------------------------------------------------------------
# Photo Upload
# ---------------------------------------------------------------------------


@packing_bp.post("/upload/photo")
@verify
@allow(role=PACKING_CREATE_ROLES)
def upload_photo():
    """上传照片

    Request: multipart/form-data with file field 'photo'

    Response:
        {
            "code": 200,
            "data": {
                "url": "/static/uploads/photos/xxx.jpg"
            }
        }
    """
    if "photo" not in request.files:
        return jsonify({"code": 400, "msg": "No photo file provided"}), 400

    file = request.files["photo"]
    url = packing_list_service.save_photo(file)

    if url is None:
        return jsonify({"code": 400, "msg": "Invalid file type"}), 400

    return jsonify({"code": 200, "data": {"url": url}})


# ---------------------------------------------------------------------------
# Packing List CRUD
# ---------------------------------------------------------------------------


@packing_bp.post("/packing-list")
@verify
@allow(role=PACKING_CREATE_ROLES)
@log(desc="Create packing list.", is_json=True)
def create_packing_list():
    """创建装箱单

    Request body:
        {
            "customer_id": 1,  // 可选
            "mark": "ABC-001",  // 必填，自动转大写
            "photos": ["/static/uploads/photos/xxx.jpg"]
        }

    Response:
        {
            "code": 200,
            "data": {
                "uid": "...",
                "list_number": "ABC-001",
                "customer_id": 1,
                "customer_name": "张三"
            }
        }
    """
    payload = get_token_payload()
    print(payload)
    if not payload:
        return jsonify({"code": 401, "msg": "Unauthorized"}), 401

    creator_id = payload.get("user_id")
    data = request.get_json() or {}

    customer_id = data.get("customer_id")
    mark = (data.get("list_number") or data.get("mark") or "").strip().upper()
    if not mark:
        return jsonify({"code": 400, "msg": "mark is required"}), 400

    photos = data.get("photos", [])

    try:
        result = packing_list_service.create_packing_list(
            creator_id=creator_id,
            mark=mark,
            customer_id=customer_id,
            photos=photos,
        )
        return jsonify({"code": 200, "data": result})
    except ValueError as e:
        return jsonify({"code": 404, "msg": str(e)}), 404


@packing_bp.get("/packing-lists")
@verify
@allow()
def get_packing_lists():
    """获取装箱单列表（分页）

    Query params:
        - p: 页码 (default: 1)
        - s: 每页数量 (default: 20)
        - customer_id: 按客户筛选
        - status: 按状态筛选 (draft/completed)
        - q: 搜索关键词（搜索唛头编号或客户名）

    Response:
        {
            "code": 200,
            "data": {
                "items": [...],
                "total": 100,
                "page": 1,
                "page_size": 20
            }
        }
    """
    page = request.args.get("p", 1, type=int)
    page_size = request.args.get("s", 20, type=int)
    customer_id = request.args.get("customer_id", type=int)
    status = request.args.get("status")
    search = request.args.get("q")

    result = packing_list_service.get_packing_lists(
        page=page,
        page_size=page_size,
        customer_id=customer_id,
        status=status,
        search=search,
    )
    return jsonify({"code": 200, "data": result})


@packing_bp.get("/packing-list/<string:uid>")
@verify
@allow()
def get_packing_list(uid):
    """获取单个装箱单详情

    Response:
        {
            "code": 200,
            "data": {
                "uid": "...",
                "list_number": "张三-0404-001",
                "customer_id": 1,
                "customer_name": "张三",
                "photos": [...],
                "creator_id": 1,
                "creator_name": "admin",
                "status": "draft",
                "create_date": "2026-04-05 10:00",
                "boxes": [...]
            }
        }
    """
    result = packing_list_service.get_packing_list(uid)
    if result is None:
        return jsonify({"code": 404, "msg": "Packing list not found"}), 404
    return jsonify({"code": 200, "data": result})


@packing_bp.put("/packing-list/<string:uid>")
@verify
@allow(role=PACKING_EDIT_ROLES)
@log(desc="Update packing list.", is_json=True)
def update_packing_list(uid):
    """更新装箱单

    Request body:
        {
            "photos": [...],
            "status": "completed"
        }
    """
    data = request.get_json() or {}

    try:
        success = packing_list_service.update_packing_list(uid, data)
    except ValueError as e:
        return jsonify({"code": 400, "msg": str(e)}), 400

    if not success:
        return jsonify({"code": 404, "msg": "Packing list not found"}), 404
    return jsonify({"code": 200, "msg": "success"})


@packing_bp.delete("/packing-list/<string:uid>")
@verify
@allow(role=["admin", "store_manager"])
@log(desc="Delete packing list.")
def delete_packing_list(uid):
    """删除装箱单（软删除）"""
    success = packing_list_service.delete_packing_list(uid)
    if not success:
        return jsonify({"code": 404, "msg": "Packing list not found"}), 404
    return jsonify({"code": 200, "msg": "success"})


@packing_bp.post("/packing-list/<string:uid>/complete")
@verify
@allow(role=PACKING_CREATE_ROLES)
@log(desc="Complete packing list.")
def complete_packing_list(uid):
    """完成装箱单"""
    success = packing_list_service.complete_packing_list(uid)
    if not success:
        return jsonify({"code": 404, "msg": "Packing list not found"}), 404
    return jsonify({"code": 200, "msg": "success"})


@packing_bp.get("/packing-list/<string:uid>/pdf")
@verify
@allow()
def export_packing_list_pdf(uid):
    """导出装箱单 PDF（中英对照）"""
    detail = packing_list_service.get_packing_list(uid)
    if detail is None:
        return jsonify({"code": 404, "msg": "Packing list not found"}), 404

    box_uids_param = (request.args.get("box_uids") or "").strip()
    if box_uids_param:
        selected_uids = {
            box_uid.strip() for box_uid in box_uids_param.split(",") if box_uid.strip()
        }
        detail = {
            **detail,
            "boxes": [
                box
                for box in (detail.get("boxes") or [])
                if box.get("uid") in selected_uids
            ],
        }

    pdf_stream = build_packing_list_pdf(detail)
    list_number = (detail.get("list_number") or detail.get("mark") or uid).strip()
    safe_name = "".join(ch for ch in list_number if ch not in '\\/:*?"<>|') or uid

    return send_file(
        pdf_stream,
        mimetype="application/pdf",
        as_attachment=False,
        download_name=f"packing-list-{safe_name}.pdf",
    )


# ---------------------------------------------------------------------------
# Box CRUD
# ---------------------------------------------------------------------------


@packing_bp.post("/packing-list/<string:list_uid>/box")
@verify
@allow(role=PACKING_CREATE_ROLES)
@log(desc="Add box to packing list.", is_json=True)
def add_box(list_uid):
    """为装箱单添加箱子

    Request body:
        {
            "item_name": "电子产品",
            "piece_count": 12,
            "weight": 5.5  // 可选，不填表示未称重
        }

    Response:
        {
            "code": 200,
            "data": {
                "uid": "...",
                "packing_list_uid": "...",
                "item_name": "电子产品",
                "piece_count": 12,
                "weight": 5.5,
                "status": 0
            }
        }
    """
    data = request.get_json() or {}
    item_name = data.get("item_name", "")
    piece_count = data.get("piece_count")
    item_details = data.get("item_details")
    remark = data.get("remark")
    weight = data.get("weight")

    if item_details is not None and not isinstance(item_details, list):
        return jsonify({"code": 400, "msg": "item_details must be a list"}), 400

    if piece_count is None and not item_details:
        return jsonify({"code": 400, "msg": "piece_count is required"}), 400

    if piece_count is not None:
        try:
            piece_count = int(piece_count)
        except (TypeError, ValueError):
            return jsonify({"code": 400, "msg": "piece_count must be an integer"}), 400

        if piece_count <= 0:
            return (
                jsonify({"code": 400, "msg": "piece_count must be greater than 0"}),
                400,
            )

    try:
        result = packing_list_service.add_box(
            list_uid,
            item_name,
            piece_count or 0,
            weight,
            item_details=item_details,
            remark=remark,
        )
        return jsonify({"code": 200, "data": result})
    except ValueError as e:
        return jsonify({"code": 404, "msg": str(e)}), 404


@packing_bp.get("/box/<string:uid>")
@verify
@allow()
def get_box(uid):
    """获取箱子详情"""
    result = packing_list_service.get_box(uid)
    if result is None:
        return jsonify({"code": 404, "msg": "Box not found"}), 404
    return jsonify({"code": 200, "data": result})


@packing_bp.put("/box/<string:uid>")
@verify
@allow(role=PACKING_EDIT_ROLES)
@log(desc="Update box.", is_json=True)
def update_box(uid):
    """更新箱子信息（品名、重量）

    Request body:
        {
            "item_name": "新品名",
            "weight": 6.0
        }
    """
    data = request.get_json() or {}
    if not isinstance(data, dict):
        return jsonify({"code": 400, "msg": "invalid request payload"}), 400

    try:
        success = packing_list_service.update_box(uid, data)
    except ValueError as e:
        return jsonify({"code": 400, "msg": str(e)}), 400

    if not success:
        return jsonify({"code": 404, "msg": "Box not found"}), 404
    return jsonify({"code": 200, "msg": "success"})


@packing_bp.put("/box/<string:uid>/weigh")
@verify
@allow(role=PACKING_CREATE_ROLES)
@log(desc="Weigh box.", is_json=True)
def weigh_box(uid):
    """称重箱子

    Request body:
        {
            "weight": 5.5
        }
    """
    data = request.get_json()
    weight = data.get("weight")

    if weight is None or weight <= 0:
        return jsonify({"code": 400, "msg": "weight must be greater than 0"}), 400

    success = packing_list_service.weigh_box(uid, weight)
    if not success:
        return jsonify({"code": 404, "msg": "Box not found"}), 404
    return jsonify({"code": 200, "msg": "success"})


@packing_bp.delete("/box/<string:uid>")
@verify
@allow(role=PACKING_EDIT_ROLES)
@log(desc="Delete box.")
def delete_box(uid):
    """删除箱子（软删除）"""
    success = packing_list_service.delete_box(uid)
    if not success:
        return jsonify({"code": 404, "msg": "Box not found"}), 404
    return jsonify({"code": 200, "msg": "success"})


# ---------------------------------------------------------------------------
# Box Workers
# ---------------------------------------------------------------------------


@packing_bp.put("/box/<string:uid>/workers")
@verify
@allow(role=PACKING_EDIT_ROLES)
@log(desc="Set box workers.", is_json=True)
def set_box_workers(uid):
    """设置箱子的打包工人（最多4人）

    Request body:
        {
            "worker_ids": [1, 2, 3]
        }
    """
    data = request.get_json()
    worker_ids = data.get("worker_ids", [])

    try:
        success = packing_list_service.set_box_workers(uid, worker_ids)
        if not success:
            return jsonify({"code": 404, "msg": "Box not found"}), 404
        return jsonify({"code": 200, "msg": "success"})
    except ValueError as e:
        return jsonify({"code": 400, "msg": str(e)}), 400


@packing_bp.post("/box/<string:uid>/workers/add")
@verify
@allow(role=PACKING_CREATE_ROLES)
@log(desc="Add box workers if empty.", is_json=True)
def add_box_workers_if_empty(uid):
    """仅在箱子尚未设置工人时，新增打包工人（最多4人）

    Request body:
        {
            "worker_ids": [1, 2]
        }
    """
    data = request.get_json() or {}
    worker_ids = data.get("worker_ids", [])

    try:
        success = packing_list_service.add_box_workers_if_empty(uid, worker_ids)
        if not success:
            return jsonify({"code": 404, "msg": "Box not found"}), 404
        return jsonify({"code": 200, "msg": "success"})
    except ValueError as e:
        error_message = str(e)
        status_code = 409 if "already set" in error_message else 400
        return jsonify({"code": status_code, "msg": error_message}), status_code


@packing_bp.get("/box/<string:uid>/workers")
@verify
@allow()
def get_box_workers(uid):
    """获取箱子的打包工人列表"""
    workers = packing_list_service.get_box_workers(uid)
    return jsonify({"code": 200, "data": workers})


# ---------------------------------------------------------------------------
# Box Assignment
# ---------------------------------------------------------------------------


@packing_bp.get("/customer/<int:customer_id>/boxes/unassigned")
@verify
@allow()
def get_unassigned_boxes(customer_id):
    """获取客户所有未分配的有效箱子，按唛头分组

    Query params:
        - valid_only: 是否只返回有效箱子（已称重），默认 true

    Response:
        {
            "code": 200,
            "data": [
                {
                    "list_number": "张三-0404-001",
                    "packing_list_uid": "...",
                    "boxes": [
                        {
                            "uid": "...",
                            "item_name": "电子产品",
                            "weight": 5.5,
                            "status": 0
                        }
                    ]
                }
            ]
        }
    """
    valid_only = request.args.get("valid_only", "true").lower() == "true"
    result = packing_list_service.get_unassigned_boxes_by_customer(
        customer_id, valid_only
    )
    return jsonify({"code": 200, "data": result})


@packing_bp.get("/boxes/unassigned")
@verify
@allow()
def get_unassigned_boxes_all():
    """获取未分配有效箱子，可选按客户和唛头过滤。

    Query params:
        - valid_only: 是否只返回有效箱子（默认 true）
        - customer_id: 可选，按客户过滤
        - q: 可选，按唛头模糊搜索
    """
    valid_only = request.args.get("valid_only", "true").lower() == "true"
    customer_id = request.args.get("customer_id", type=int)
    mark_search = request.args.get("q")

    result = packing_list_service.get_unassigned_boxes(
        valid_only=valid_only,
        customer_id=customer_id,
        mark_search=mark_search,
    )
    return jsonify({"code": 200, "data": result})


@packing_bp.post("/boxes/assign")
@verify
@allow(role=BOX_ASSIGN_ROLES)
@log(desc="Assign boxes to order.", is_json=True)
def assign_boxes():
    """批量分配箱子到订单

    Request body:
        {
            "box_uids": ["uid1", "uid2"],
            "order_uid": "..."
        }

    Response:
        {
            "code": 200,
            "data": {
                "success": ["uid1", "uid2"],
                "failed": [{"uid": "uid3", "error": "..."}]
            }
        }
    """
    data = request.get_json()
    box_uids = data.get("box_uids", [])
    order_uid = data.get("order_uid")

    if not box_uids:
        return jsonify({"code": 400, "msg": "box_uids is required"}), 400
    if not order_uid:
        return jsonify({"code": 400, "msg": "order_uid is required"}), 400

    result = packing_list_service.batch_assign_boxes(box_uids, order_uid)
    return jsonify({"code": 200, "data": result})


@packing_bp.post("/packing-list/<string:uid>/ship")
@verify
@allow(role=BOX_SHIP_ROLES)
@log(desc="Ship selected boxes.", is_json=True)
def ship_selected_boxes(uid):
    """装箱单出货：仅允许将待出库箱子置为已出库。"""
    data = request.get_json() or {}
    box_uids = data.get("box_uids") or []

    if not isinstance(box_uids, list) or len(box_uids) == 0:
        return jsonify({"code": 400, "msg": "box_uids is required"}), 400

    result = packing_list_service.ship_boxes(uid, box_uids)
    return jsonify({"code": 200, "data": result})


@packing_bp.post("/box/<string:uid>/undo-ship")
@verify
@allow(role=PACKING_EDIT_ROLES)
@log(desc="Undo box shipping.")
def undo_ship_box(uid):
    """撤销单箱出货：将已出库回退为待出库。"""
    try:
        success = packing_list_service.undo_ship_box(uid)
    except ValueError as e:
        return jsonify({"code": 400, "msg": str(e)}), 400

    if not success:
        return jsonify({"code": 404, "msg": "Box not found"}), 404
    return jsonify({"code": 200, "msg": "success"})


@packing_bp.get("/orders/<string:order_uid>/boxes")
@verify
@allow()
def get_assigned_boxes_by_order(order_uid):
    """获取指定订单下已分配的箱子列表。"""
    result = packing_list_service.get_boxes_by_order(order_uid)
    return jsonify({"code": 200, "data": result})


# ---------------------------------------------------------------------------
# Box Label (for printing)
# ---------------------------------------------------------------------------


@packing_bp.get("/box/<string:uid>/label")
def get_box_label(uid):
    """获取箱子标签信息（用于打印）

    Response:
        {
            "code": 200,
            "data": {
                "uid": "...",
                "list_number": "张三-0404-001",
                "item_name": "电子产品",
                "piece_count": 12,
                "weight": 5.5,
                "customer_name": "张三"
            }
        }
    """
    box = packing_list_service.get_box(uid)
    if box is None:
        return jsonify({"code": 404, "msg": "Box not found"}), 404

    # 获取装箱单信息以获取客户名
    packing_list = packing_list_service.get_packing_list(box["packing_list_uid"])

    label_data = {
        "uid": box["uid"],
        "list_number": box.get("list_number")
        or (packing_list["list_number"] if packing_list else ""),
        "item_name": box["item_name"],
        "item_details": box.get("item_details", []),
        "remark": box.get("remark"),
        "piece_count": box.get("piece_count", 0),
        "weight": box["weight"],
        "customer_name": packing_list["customer_name"] if packing_list else "",
    }

    return jsonify({"code": 200, "data": label_data})
