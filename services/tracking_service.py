"""Read-only order parcel tracking, independent of cargo business state."""
from datetime import datetime, timezone

from data.DB import CargoTable, OrderTable
from data.database import SessionFactory
from services.order_edit_policy import cargo_is_outbound_or_later
from utils.l7track import TrackingQueryError, query_tracking_infos


# Keep these labels aligned with frontend/src/common/trackStatus.js.
SUB_STATUS_TEXT = {
    "InfoReceived": "收到信息",
    "InTransit_PickedUp": "已揽收",
    "InTransit_Other": "运输途中",
    "InTransit_Departure": "已离港",
    "InTransit_Arrival": "已到港",
    "InTransit_CustomsProcessing": "清关中",
    "InTransit_CustomsReleased": "清关完成",
    "InTransit_CustomsRequiringInformation": "需要资料",
    "Expired_Other": "运输过久",
    "AvailableForPickup_Other": "到达待取",
    "OutForDelivery_Other": "派送途中",
    "DeliveryFailure_Other": "投递失败",
    "DeliveryFailure_NoBody": "找不到收件人",
    "DeliveryFailure_Security": "投递失败(安全原因)",
    "DeliveryFailure_Rejected": "拒收",
    "DeliveryFailure_InvalidAddress": "地址错误",
    "Delivered_Other": "成功签收",
    "Exception_Other": "其它情况",
    "Exception_Returning": "退件中",
    "Exception_Returned": "退件签收",
    "Exception_NoBody": "找不到收件人",
    "Exception_Security": "安全原因",
    "Exception_Damage": "损坏",
    "Exception_Rejected": "拒收",
    "Exception_Delayed": "延误",
    "Exception_Lost": "丢失",
    "Exception_Destroyed": "销毁",
    "Exception_Cancel": "取消",
}
STATUS_TEXT = {
    "NotFound": "暂无物流轨迹",
    "InfoReceived": "收到信息",
    "InTransit": "运输途中",
    "Expired": "运输过久",
    "AvailableForPickup": "到达待取",
    "OutForDelivery": "派送途中",
    "DeliveryFailure": "投递失败",
    "Delivered": "成功签收",
    "Exception": "物流异常",
}


def _invalid_response():
    return TrackingQueryError(502, "物流服务返回无效响应")


def _result_record(payload, waybill_id):
    data = payload["data"]
    accepted = [row for row in data["accepted"] if row.get("number") == waybill_id]
    if len(accepted) > 1:
        raise TrackingQueryError(400, "此转单号匹配多个承运商，无法确定物流状态")
    if accepted:
        return accepted[0]
    errors = data.get("errors", []) + payload.get("errors", [])
    for row in data["rejected"]:
        if row.get("number") != waybill_id:
            continue
        error = row.get("error")
        if not isinstance(error, dict) or type(error.get("code")) is not int:
            raise _invalid_response()
        errors.append(error)
    if errors:
        # An explicit provider or input failure is more informative than an
        # unregistered result if several carriers rejected the same number.
        failures = [TrackingQueryError.from_provider_code(error.get("code")) for error in errors]
        raise next((failure for failure in failures if failure.code != 404), failures[0])
    raise TrackingQueryError(404, "未查询到此转单号的物流信息")


def _latest_event(event):
    if event is None:
        return None
    if not isinstance(event, dict):
        raise _invalid_response()
    event_time = event.get("time_utc") or event.get("time_iso")
    if not event_time and event.get("time_raw") is not None:
        raw = event["time_raw"]
        if not isinstance(raw, dict):
            raise _invalid_response()
        parts = [raw.get("date"), raw.get("time")]
        if any(part is not None and not isinstance(part, str) for part in parts):
            raise _invalid_response()
        event_time = " ".join(part for part in parts if part) or None
    location, description = event.get("location"), event.get("description")
    if any(value is not None and not isinstance(value, str)
           for value in (event_time, location, description)):
        raise _invalid_response()
    return {"time": event_time or None, "location": location, "description": description}


def _parcel_tracking(record):
    if "track_info" not in record:
        raise _invalid_response()
    track_info = record["track_info"]
    if track_info is None:
        status, sub_status, description, latest_event = "NotFound", None, "", None
    else:
        if not isinstance(track_info, dict) or "latest_status" not in track_info:
            raise _invalid_response()
        latest_status = track_info["latest_status"]
        if latest_status is None:
            status, sub_status, description = "NotFound", None, ""
        else:
            if (not isinstance(latest_status, dict)
                    or not isinstance(latest_status.get("status"), str)
                    or not latest_status["status"]):
                raise _invalid_response()
            status = latest_status["status"]
            sub_status = latest_status.get("sub_status")
            description = latest_status.get("sub_status_descr", "")
            if ((sub_status is not None and not isinstance(sub_status, str))
                    or (description is not None and not isinstance(description, str))):
                raise _invalid_response()
        latest_event = _latest_event(track_info.get("latest_event"))
    status_text = (STATUS_TEXT["NotFound"] if status == "NotFound" else
                   SUB_STATUS_TEXT.get(sub_status, STATUS_TEXT.get(status, "未知物流状态")))
    return {"status": status, "sub_status": sub_status, "status_text": status_text,
            "description": description, "latest_event": latest_event, "error": None}


def _failed_tracking(error):
    return {"status": None, "sub_status": None, "status_text": None,
            "description": None, "latest_event": None,
            "error": {"code": error.code, "msg": error.msg}}


def _query_numbers(numbers):
    results = {}
    for start in range(0, len(numbers), 40):
        batch = numbers[start:start + 40]
        try:
            payload = query_tracking_infos(batch)
        except TrackingQueryError as exc:
            results.update({number: _failed_tracking(exc) for number in batch})
            continue
        for number in batch:
            try:
                results[number] = _parcel_tracking(_result_record(payload, number))
            except TrackingQueryError as exc:
                results[number] = _failed_tracking(exc)
    return results


def get_tracking(order_id: str) -> dict:
    """Resolve an exact business order number and query its parcels without cache."""
    if (not isinstance(order_id, str) or not order_id.strip()
            or len(order_id.strip()) > 128
            or any(ord(char) < 32 or ord(char) == 127 for char in order_id)):
        return {"code": 400, "msg": "订单号无效"}
    order_id = order_id.strip()
    with SessionFactory() as session:
        orders = session.query(OrderTable).filter(
            OrderTable.order_id == order_id, OrderTable.archive.is_(False),
        ).limit(2).all()
        if not orders:
            return {"code": 404, "msg": "订单不存在"}
        if len(orders) > 1:
            return {"code": 409, "msg": "订单号对应多个未归档订单，请先处理重复订单号"}
        order_uid = orders[0].uid
        order_id = orders[0].order_id
        cargos = session.query(CargoTable).filter(
            CargoTable.target_order_uid == order_uid, CargoTable.archive.is_(False),
        ).order_by(CargoTable.box_number.is_(None), CargoTable.box_number.asc(), CargoTable.uid.asc()).all()
        parcels = [{
            "uid": cargo.uid,
            "box_number": cargo.box_number,
            "item_name": cargo.item_name or cargo.real_en_name,
            "weight": cargo.weight,
            "transfer_id": cargo.transfer_id,
            "waybill_id": cargo.waybill_id,
            "warehouse_status": cargo.status,
            "warehouse_status_text": "已出库" if cargo_is_outbound_or_later(cargo.status) else "待出库",
            "tracking": None,
        } for cargo in cargos]

    # Release the database session before any potentially slow upstream request.
    numbers = list(dict.fromkeys((parcel["waybill_id"] or "").strip() for parcel in parcels
                                if (parcel["waybill_id"] or "").strip()))
    results = _query_numbers(numbers)
    for parcel in parcels:
        number = (parcel["waybill_id"] or "").strip()
        if number:
            parcel["tracking"] = results[number]
    return {
        "code": 200,
        "data": parcels,
        "total": len(parcels),
        "order_id": order_id,
        "order_uid": order_uid,
        "queried_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "tracking_complete": all(result["error"] is None for result in results.values()),
    }
