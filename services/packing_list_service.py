"""
Packing List Service - 装箱单业务逻辑

处理装箱单和箱子的业务逻辑，包括：
- 装箱单创建、查询、更新
- 箱子管理
- 箱子分配到订单
"""

import json
import os
import time
from typing import List, Optional
from werkzeug.datastructures import FileStorage

from data.packing import packing_list_model, box_model
from services.box_validator import default_validator


# ---------------------------------------------------------------------------
# Photo Upload Configuration
# ---------------------------------------------------------------------------

UPLOAD_FOLDER = "static/uploads/photos"
ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}


def allowed_file(filename: str) -> bool:
    """检查文件扩展名是否允许"""
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def save_photo(file: FileStorage) -> Optional[str]:
    """保存上传的照片

    Args:
        file: 上传的文件对象

    Returns:
        保存后的文件路径（相对路径），失败返回 None
    """
    if not file or not file.filename:
        return None

    if not allowed_file(file.filename):
        return None

    # 确保目录存在
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)

    # 生成唯一文件名
    ext = file.filename.rsplit(".", 1)[1].lower()
    filename = f"{int(time.time() * 1000)}_{os.urandom(4).hex()}.{ext}"
    filepath = os.path.join(UPLOAD_FOLDER, filename)

    file.save(filepath)

    # 返回相对路径（用于前端访问）
    return f"/static/uploads/photos/{filename}"


# ---------------------------------------------------------------------------
# Packing List Service Functions
# ---------------------------------------------------------------------------


def create_packing_list(
    creator_id: int,
    mark: str,
    customer_id: Optional[int] = None,
    photos: List[str] = None,
) -> dict:
    """创建装箱单

    Args:
        creator_id: 创建人ID
        mark: 用户输入唛头
        customer_id: 客户ID（可选）
        photos: 照片路径列表

    Returns:
        创建的装箱单信息
    """
    photos_json = json.dumps(photos or [])
    return packing_list_model.create(
        creator_id=creator_id,
        mark=mark,
        customer_id=customer_id,
        photos=photos_json,
    )


def get_packing_list(uid: str) -> Optional[dict]:
    """获取单个装箱单详情"""
    return packing_list_model.read(uid)


def get_packing_lists(
    page: int = 1,
    page_size: int = 20,
    customer_id: int = None,
    status: str = None,
    search: str = None,
) -> dict:
    """获取装箱单列表（分页）

    Args:
        page: 页码
        page_size: 每页数量
        customer_id: 按客户筛选
        status: 按状态筛选
        search: 搜索关键词（搜索唛头编号）

    Returns:
        {
            "items": [...],
            "total": int,
            "page": int,
            "page_size": int,
        }
    """
    all_lists = packing_list_model.read()

    # 筛选
    if customer_id:
        all_lists = [pl for pl in all_lists if pl["customer_id"] == customer_id]

    if status:
        all_lists = [pl for pl in all_lists if pl["status"] == status]

    if search:
        search_lower = search.lower()
        all_lists = [
            pl
            for pl in all_lists
            if search_lower in (pl.get("list_number") or "").lower()
            or search_lower in (pl.get("customer_name") or "").lower()
        ]

    # 分页
    total = len(all_lists)
    start = (page - 1) * page_size
    end = start + page_size
    items = all_lists[start:end]

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def update_packing_list(uid: str, data: dict) -> bool:
    """更新装箱单"""
    return packing_list_model.update(uid, data)


def delete_packing_list(uid: str) -> bool:
    """删除装箱单"""
    return packing_list_model.delete(uid)


def complete_packing_list(uid: str) -> bool:
    """完成装箱单"""
    return packing_list_model.update(uid, {"status": "completed"})


# ---------------------------------------------------------------------------
# Box Service Functions
# ---------------------------------------------------------------------------


def add_box(
    packing_list_uid: str,
    item_name: str,
    piece_count: int,
    weight: float = None,
    item_details: Optional[List[dict]] = None,
    remark: Optional[str] = None,
) -> dict:
    """添加箱子到装箱单"""
    return box_model.create(
        packing_list_uid,
        item_name,
        piece_count,
        weight,
        item_details=item_details,
        remark=remark,
    )


def update_box(uid: str, data: dict) -> bool:
    """更新箱子信息"""
    return box_model.update(uid, data)


def weigh_box(uid: str, weight: float) -> bool:
    """称重箱子"""
    return box_model.update(uid, {"weight": weight})


def delete_box(uid: str) -> bool:
    """删除箱子"""
    return box_model.delete(uid)


def set_box_workers(box_uid: str, worker_ids: List[int]) -> bool:
    """设置箱子的打包工人"""
    return box_model.set_workers(box_uid, worker_ids)


def add_box_workers_if_empty(box_uid: str, worker_ids: List[int]) -> bool:
    """仅在箱子尚未设置工人时，新增工人"""
    return box_model.add_workers_if_empty(box_uid, worker_ids)


def get_box_workers(box_uid: str) -> List[dict]:
    """获取箱子的打包工人"""
    return box_model.get_workers(box_uid)


def get_box(uid: str) -> Optional[dict]:
    """获取箱子详情"""
    return box_model.read(uid)


# ---------------------------------------------------------------------------
# Box Assignment Service Functions
# ---------------------------------------------------------------------------


def get_unassigned_boxes_by_customer(
    customer_id: int, valid_only: bool = True
) -> List[dict]:
    """获取客户所有未分配的有效箱子，按唛头分组

    Args:
        customer_id: 客户ID
        valid_only: 是否只返回有效箱子（已称重）

    Returns:
        [
            {
                "list_number": "张三-0404-001",
                "packing_list_uid": "...",
                "boxes": [...]
            },
            ...
        ]
    """
    return box_model.get_unassigned_by_customer(customer_id, valid_only)


def get_unassigned_boxes(
    valid_only: bool = True,
    customer_id: Optional[int] = None,
    mark_search: Optional[str] = None,
) -> List[dict]:
    """获取未分配箱子，可按客户和唛头过滤。"""
    return box_model.get_unassigned(
        valid_only=valid_only,
        customer_id=customer_id,
        mark_search=mark_search,
    )


def assign_box_to_order(box_uid: str, order_uid: str) -> bool:
    """将箱子分配到订单"""
    return box_model.assign_to_order(box_uid, order_uid)


def batch_assign_boxes(box_uids: List[str], order_uid: str) -> dict:
    """批量分配箱子到订单

    Returns:
        {
            "success": ["uid1", "uid2"],
            "failed": [{"uid": "uid3", "error": "..."}]
        }
    """
    return box_model.batch_assign(box_uids, order_uid)


def get_boxes_by_order(order_uid: str) -> List[dict]:
    """获取已分配到指定订单的箱子。"""
    return box_model.get_by_order_uid(order_uid)


def ship_boxes(packing_list_uid: str, box_uids: List[str]) -> dict:
    """批量出货：将待出库箱子更新为已出库。"""
    return box_model.batch_ship(packing_list_uid, box_uids)


def undo_ship_box(uid: str) -> bool:
    """撤销单箱出货：将已出库回退为待出库。"""
    return box_model.undo_ship(uid)


# ---------------------------------------------------------------------------
# Box Validation
# ---------------------------------------------------------------------------


def is_box_valid(box: dict) -> bool:
    """检查箱子是否有效"""
    return default_validator.is_valid(box)


def validate_box(box: dict) -> dict:
    """验证箱子并返回详细结果"""
    return default_validator.validate(box)


def filter_valid_boxes(boxes: List[dict]) -> List[dict]:
    """过滤出有效箱子"""
    return default_validator.filter_valid_boxes(boxes)
