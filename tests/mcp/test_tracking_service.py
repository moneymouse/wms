"""Order tracking tests use isolated SQLite and mocked 17TRACK batches only."""
import copy
from datetime import datetime, timezone
from unittest.mock import Mock, call

import pytest

from data.DB import CargoTable, OrderTable
from services import tracking_service
from utils.l7track import TrackingQueryError


ORDER_ID = "BUSINESS-ORDER-2026"
ORDER_UID = "internal-order-001"
PARCEL_FIELDS = {"uid", "box_number", "item_name", "weight", "transfer_id", "waybill_id",
                 "warehouse_status", "warehouse_status_text", "tracking"}
TRACKING_FIELDS = {"status", "sub_status", "status_text", "description", "latest_event", "error"}


def accepted(number, status="Delivered", sub_status="Delivered_Other", carrier=3011):
    return {
        "number": number, "carrier": carrier, "tag": "not-the-cargo-uid",
        "track_info": {
            "latest_status": {"status": status, "sub_status": sub_status,
                              "sub_status_descr": "Provider latest status"},
            "latest_event": {"time_iso": "2026-10-07T01:30:00Z", "location": "Shanghai",
                             "description": "Delivered to recipient", "extra": "internal-event-detail"},
            "tracking": {"providers": [{"events": [{"description": "large-history"}]}]},
            "recipient": {"address": "private-address"},
            "provider_extension": {"kept_only_upstream": True},
        },
    }


def envelope(*records, rejected=None, errors=None):
    return {"code": 0, "data": {"accepted": list(records), "rejected": rejected or [],
                                "errors": errors or []}}


@pytest.fixture
def world(mcp_db, monkeypatch):
    factory = mcp_db["factory"]
    monkeypatch.setattr(tracking_service, "SessionFactory", factory)
    provider = Mock(side_effect=AssertionError("Unexpected provider query"))
    monkeypatch.setattr(tracking_service, "query_tracking_infos", provider)
    with factory() as session:
        session.add(OrderTable(uid=ORDER_UID, order_id=ORDER_ID, archive=False))
        session.commit()
    return {"factory": factory, "provider": provider}


def add_cargos(world, *records):
    with world["factory"]() as session:
        for record in records:
            defaults = {"target_order_uid": ORDER_UID, "archive": False, "status": 0,
                        "item_name": "Box contents", "weight": 12.5, "transfer_id": "ORIGINAL-1"}
            defaults.update(record)
            session.add(CargoTable(**defaults))
        session.commit()


def test_business_order_number_returns_compact_parcels_without_changing_state(world):
    add_cargos(world, {"uid": "cargo-1", "box_number": 1, "waybill_id": "WAYBILL-1", "status": 0})
    payload = envelope(accepted("WAYBILL-1"))
    original = copy.deepcopy(payload)
    world["provider"].side_effect = None
    world["provider"].return_value = payload
    started = datetime.now(timezone.utc)
    result = tracking_service.get_tracking(f"  {ORDER_ID}  ")
    assert set(result) == {"code", "data", "total", "order_id", "order_uid", "queried_at", "tracking_complete"}
    assert result["code"] == 200
    assert result["order_id"] == ORDER_ID
    assert result["order_uid"] == ORDER_UID
    assert result["total"] == 1
    assert result["tracking_complete"] is True
    assert result["queried_at"].endswith("Z")
    assert started <= datetime.fromisoformat(result["queried_at"].replace("Z", "+00:00")) <= datetime.now(timezone.utc)
    parcel = result["data"][0]
    assert set(parcel) == PARCEL_FIELDS
    assert parcel["uid"] == "cargo-1"
    assert parcel["warehouse_status"] == 0
    assert parcel["warehouse_status_text"] == "待出库"
    assert set(parcel["tracking"]) == TRACKING_FIELDS
    assert parcel["tracking"]["status"] == "Delivered"
    assert parcel["tracking"]["status_text"] == "成功签收"
    assert parcel["tracking"]["error"] is None
    assert parcel["tracking"]["latest_event"] == {
        "time": "2026-10-07T01:30:00Z", "location": "Shanghai", "description": "Delivered to recipient",
    }
    assert "track_info" not in str(result)
    assert "large-history" not in str(result)
    assert "private-address" not in str(result)
    assert "not-the-cargo-uid" not in str(result)
    assert payload == original
    with world["factory"]() as session:
        cargo = session.query(CargoTable).filter_by(uid="cargo-1").one()
        assert cargo.status == 0
        assert cargo.waybill_id == "WAYBILL-1"
    world["provider"].assert_called_once_with(["WAYBILL-1"])


def test_no_waybill_keeps_warehouse_state_and_does_not_query(world):
    add_cargos(world, {"uid": "unshipped", "box_number": 2, "waybill_id": "", "status": 0},
               {"uid": "shipped", "box_number": 1, "waybill_id": None, "status": 1})
    result = tracking_service.get_tracking(ORDER_ID)
    assert result["code"] == 200
    assert result["tracking_complete"] is True
    assert result["total"] == 2
    assert [parcel["uid"] for parcel in result["data"]] == ["shipped", "unshipped"]
    assert [parcel["warehouse_status_text"] for parcel in result["data"]] == ["已出库", "待出库"]
    assert all(parcel["tracking"] is None for parcel in result["data"])
    world["provider"].assert_not_called()


@pytest.mark.parametrize("warehouse_status,label", [(2, "已出库"), ("InTransit_Other", "已出库"),
                                                   ("pending_outbound", "待出库")])
def test_existing_later_or_pending_warehouse_states_keep_business_semantics(world, warehouse_status, label):
    add_cargos(world, {"uid": "cargo-1", "waybill_id": "", "status": warehouse_status})
    parcel = tracking_service.get_tracking(ORDER_ID)["data"][0]
    assert parcel["warehouse_status"] == warehouse_status
    assert parcel["warehouse_status_text"] == label
    assert parcel["tracking"] is None
    world["provider"].assert_not_called()


def test_empty_order_is_success_without_provider_request(world):
    result = tracking_service.get_tracking(ORDER_ID)
    assert result["code"] == 200
    assert result["data"] == []
    assert result["total"] == 0
    assert result["tracking_complete"] is True
    world["provider"].assert_not_called()


@pytest.mark.parametrize("order_id", ["MISSING", ORDER_UID, "BUSINESS-ORDER"])
def test_missing_uid_and_partial_order_number_do_not_resolve(world, order_id):
    assert tracking_service.get_tracking(order_id) == {"code": 404, "msg": "订单不存在"}
    world["provider"].assert_not_called()


def test_archived_order_is_not_returned(world):
    with world["factory"]() as session:
        session.query(OrderTable).filter_by(uid=ORDER_UID).update({"archive": True})
        session.commit()
    assert tracking_service.get_tracking(ORDER_ID) == {"code": 404, "msg": "订单不存在"}
    world["provider"].assert_not_called()


def test_duplicate_active_business_order_number_is_conflict(world):
    with world["factory"]() as session:
        session.add(OrderTable(uid="duplicate-order", order_id=ORDER_ID, archive=False))
        session.commit()
    assert tracking_service.get_tracking(ORDER_ID) == {
        "code": 409, "msg": "订单号对应多个未归档订单，请先处理重复订单号",
    }
    world["provider"].assert_not_called()


def test_archived_duplicate_does_not_conflict_and_foreign_cargo_is_excluded(world):
    with world["factory"]() as session:
        session.add_all([OrderTable(uid="old-order", order_id=ORDER_ID, archive=True),
                         OrderTable(uid="another-order", order_id="OTHER", archive=False)])
        session.commit()
    add_cargos(world, {"uid": "own-b", "box_number": 2},
               {"uid": "own-c", "box_number": None, "item_name": None, "real_en_name": "Legacy item"},
               {"uid": "own-a", "box_number": 2},
               {"uid": "archived", "archive": True, "waybill_id": "DO-NOT-QUERY"},
               {"uid": "foreign", "target_order_uid": "another-order", "waybill_id": "DO-NOT-QUERY"})
    result = tracking_service.get_tracking(ORDER_ID)
    assert result["code"] == 200
    assert [parcel["uid"] for parcel in result["data"]] == ["own-a", "own-b", "own-c"]
    assert result["data"][2]["item_name"] == "Legacy item"
    world["provider"].assert_not_called()


def test_shared_waybill_is_queried_once_and_matches_number_instead_of_tag(world):
    add_cargos(world, {"uid": "cargo-a", "box_number": 1, "waybill_id": "SHARED", "status": 0},
               {"uid": "cargo-b", "box_number": 2, "waybill_id": "SHARED", "status": 1})
    world["provider"].side_effect = None
    world["provider"].return_value = envelope(accepted("SHARED"))
    result = tracking_service.get_tracking(ORDER_ID)
    world["provider"].assert_called_once_with(["SHARED"])
    assert result["total"] == 2
    assert result["data"][0]["tracking"] == result["data"][1]["tracking"]
    assert result["data"][0]["tracking"]["status_text"] == "成功签收"
    assert [parcel["warehouse_status"] for parcel in result["data"]] == [0, 1]


def test_repeated_order_queries_have_no_cache(world):
    add_cargos(world, {"uid": "cargo-1", "waybill_id": "ONE"})
    world["provider"].side_effect = None
    world["provider"].return_value = envelope(accepted("ONE"))
    assert tracking_service.get_tracking(ORDER_ID)["code"] == 200
    assert tracking_service.get_tracking(ORDER_ID)["code"] == 200
    assert world["provider"].call_count == 2


def test_large_order_is_split_into_two_batches_of_at_most_40(world):
    add_cargos(world, *[{"uid": f"cargo-{index:02}", "box_number": index,
                        "waybill_id": f"WAYBILL-{index:02}"} for index in range(41, 0, -1)])
    world["provider"].side_effect = lambda numbers: envelope(*(accepted(number) for number in reversed(numbers)))
    result = tracking_service.get_tracking(ORDER_ID)
    assert result["total"] == 41
    assert result["tracking_complete"] is True
    assert world["provider"].call_args_list == [
        call([f"WAYBILL-{index:02}" for index in range(1, 41)]), call(["WAYBILL-41"]),
    ]
    assert all(parcel["tracking"]["status_text"] == "成功签收" for parcel in result["data"])


def test_one_batch_failure_keeps_all_parcels_and_other_batch_results(world):
    add_cargos(world, *[{"uid": f"cargo-{index:02}", "box_number": index,
                        "waybill_id": f"WAYBILL-{index:02}"} for index in range(1, 42)])
    world["provider"].side_effect = [TrackingQueryError(504, "物流查询超时，请稍后重试"),
                                    envelope(accepted("WAYBILL-41"))]
    result = tracking_service.get_tracking(ORDER_ID)
    assert result["code"] == 200
    assert result["total"] == 41
    assert result["tracking_complete"] is False
    assert all(parcel["tracking"]["error"]["code"] == 504 for parcel in result["data"][:40])
    assert result["data"][40]["tracking"]["error"] is None
    assert result["data"][40]["tracking"]["status_text"] == "成功签收"


def test_partial_rejection_does_not_discard_successful_number(world):
    add_cargos(world, {"uid": "cargo-ok", "box_number": 1, "waybill_id": "REGISTERED"},
               {"uid": "cargo-error", "box_number": 2, "waybill_id": "UNREGISTERED"},
               {"uid": "cargo-no-number", "box_number": 3, "waybill_id": ""})
    payload = envelope(accepted("REGISTERED"), rejected=[{
        "number": "UNREGISTERED", "tag": "irrelevant-tag",
        "error": {"code": -18019902, "message": "Do not leak provider message"},
    }])
    original = copy.deepcopy(payload)
    world["provider"].side_effect = None
    world["provider"].return_value = payload
    result = tracking_service.get_tracking(ORDER_ID)
    assert result["code"] == 200
    assert result["total"] == 3
    assert result["tracking_complete"] is False
    assert result["data"][0]["tracking"]["status_text"] == "成功签收"
    assert result["data"][1]["tracking"]["error"] == {"code": 404, "msg": "此转单号尚未注册物流追踪"}
    assert result["data"][2]["tracking"] is None
    assert "Do not leak" not in str(result)
    assert payload == original


@pytest.mark.parametrize("status,sub_status,label", [
    ("Exception", "Exception_Returned", "退件签收"),
    ("InTransit", "InTransit_CustomsReleased", "清关完成"),
    ("DeliveryFailure", "DeliveryFailure_Security", "投递失败(安全原因)"),
    ("NotFound", "NotFound_Other", "暂无物流轨迹"),
    ("InTransit", "FutureSubStatus", "运输途中"),
    ("FutureStatus", "FutureSubStatus", "未知物流状态"),
])
def test_tracking_statuses_and_fallback_do_not_replace_warehouse_state(world, status, sub_status, label):
    add_cargos(world, {"uid": "cargo-1", "waybill_id": "ONE", "status": 1})
    world["provider"].side_effect = None
    world["provider"].return_value = envelope(accepted("ONE", status, sub_status))
    result = tracking_service.get_tracking(ORDER_ID)
    parcel = result["data"][0]
    assert parcel["warehouse_status"] == 1
    assert parcel["warehouse_status_text"] == "已出库"
    assert parcel["tracking"]["status"] == status
    assert parcel["tracking"]["sub_status"] == sub_status
    assert parcel["tracking"]["status_text"] == label
    assert parcel["tracking"]["error"] is None
    assert result["tracking_complete"] is True


@pytest.mark.parametrize("status,label", [
    ("NotFound", "暂无物流轨迹"), ("InfoReceived", "收到信息"), ("InTransit", "运输途中"),
    ("Expired", "运输过久"), ("AvailableForPickup", "到达待取"), ("OutForDelivery", "派送途中"),
    ("DeliveryFailure", "投递失败"), ("Delivered", "成功签收"), ("Exception", "物流异常"),
])
def test_all_nine_main_statuses_have_chinese_labels(world, status, label):
    add_cargos(world, {"uid": "cargo-1", "waybill_id": "ONE"})
    world["provider"].side_effect = None
    world["provider"].return_value = envelope(accepted("ONE", status, None))
    assert tracking_service.get_tracking(ORDER_ID)["data"][0]["tracking"]["status_text"] == label


@pytest.mark.parametrize("track_info", [None, {"latest_status": None}])
def test_registered_without_track_is_successful_not_found(world, track_info):
    add_cargos(world, {"uid": "cargo-1", "waybill_id": "ONE"})
    record = accepted("ONE")
    record["track_info"] = track_info
    world["provider"].side_effect = None
    world["provider"].return_value = envelope(record)
    result = tracking_service.get_tracking(ORDER_ID)
    tracking = result["data"][0]["tracking"]
    assert tracking["status"] == "NotFound"
    assert tracking["status_text"] == "暂无物流轨迹"
    assert tracking["latest_event"] is None
    assert tracking["error"] is None
    assert result["tracking_complete"] is True


@pytest.mark.parametrize("code,msg", [(429, "物流服务请求过于频繁，请稍后重试"),
                                     (502, "物流服务暂时不可用，请稍后重试"),
                                     (504, "物流查询超时，请稍后重试")])
def test_upstream_batch_failure_is_per_parcel_error_not_order_failure(world, code, msg):
    add_cargos(world, {"uid": "cargo-1", "waybill_id": "ONE", "status": 1})
    world["provider"].side_effect = TrackingQueryError(code, msg)
    result = tracking_service.get_tracking(ORDER_ID)
    assert result["code"] == 200
    assert result["tracking_complete"] is False
    parcel = result["data"][0]
    assert parcel["warehouse_status"] == 1
    assert parcel["tracking"] == {"status": None, "sub_status": None, "status_text": None,
                                  "description": None, "latest_event": None, "error": {"code": code, "msg": msg}}


def test_multiple_carriers_are_reported_without_silently_selecting_first(world):
    add_cargos(world, {"uid": "cargo-1", "waybill_id": "ONE"})
    world["provider"].side_effect = None
    world["provider"].return_value = envelope(accepted("ONE", carrier=3011), accepted("ONE", carrier=3012))
    result = tracking_service.get_tracking(ORDER_ID)
    assert result["tracking_complete"] is False
    assert result["data"][0]["tracking"]["error"] == {
        "code": 400, "msg": "此转单号匹配多个承运商，无法确定物流状态",
    }


@pytest.mark.parametrize("event,expected_time", [
    ({"time_utc": "2026-10-07T01:30:00Z", "time_iso": "ignored"}, "2026-10-07T01:30:00Z"),
    ({"time_iso": "2026-10-07T09:30:00+08:00"}, "2026-10-07T09:30:00+08:00"),
    ({"time_raw": {"date": "2026-10-07", "time": "09:30:00"}}, "2026-10-07 09:30:00"),
    ({"description": "Only description"}, None),
])
def test_latest_event_time_precedence_and_projection(world, event, expected_time):
    add_cargos(world, {"uid": "cargo-1", "waybill_id": "ONE"})
    record = accepted("ONE")
    record["track_info"]["latest_event"] = {**event, "location": "Shanghai", "hidden": "not-returned"}
    world["provider"].side_effect = None
    world["provider"].return_value = envelope(record)
    latest = tracking_service.get_tracking(ORDER_ID)["data"][0]["tracking"]["latest_event"]
    assert set(latest) == {"time", "location", "description"}
    assert latest["time"] == expected_time
    assert latest["location"] == "Shanghai"
    assert latest["description"] == event.get("description")


def test_missing_or_invalid_provider_details_fail_per_parcel(world):
    add_cargos(world, {"uid": "cargo-1", "waybill_id": "ONE"},
               {"uid": "cargo-2", "waybill_id": "TWO"},
               {"uid": "cargo-3", "waybill_id": "THREE"})
    malformed = accepted("ONE")
    malformed["track_info"]["latest_event"]["location"] = {"unexpected": "object"}
    missing = accepted("TWO")
    del missing["track_info"]
    world["provider"].side_effect = None
    world["provider"].return_value = envelope(malformed, missing)
    result = tracking_service.get_tracking(ORDER_ID)
    assert result["code"] == 200
    assert result["total"] == 3
    assert result["tracking_complete"] is False
    assert [parcel["tracking"]["error"]["code"] for parcel in result["data"]] == [502, 502, 404]


def test_database_session_is_closed_before_provider_call(world, monkeypatch):
    add_cargos(world, {"uid": "cargo-1", "waybill_id": "ONE"})
    state = {"open": False}

    class ObservedSession:
        def __enter__(self):
            state["open"] = True
            self.session = world["factory"]()
            return self.session

        def __exit__(self, *args):
            self.session.close()
            state["open"] = False

    def query(numbers):
        assert state["open"] is False
        return envelope(accepted("ONE"))

    monkeypatch.setattr(tracking_service, "SessionFactory", ObservedSession)
    world["provider"].side_effect = query
    assert tracking_service.get_tracking(ORDER_ID)["code"] == 200
    assert state["open"] is False


@pytest.mark.parametrize("order_id", [None, "", "   ", "x" * 129, "ABC\n", True])
def test_invalid_business_order_number_does_not_call_provider(world, order_id):
    assert tracking_service.get_tracking(order_id) == {"code": 400, "msg": "订单号无效"}
    world["provider"].assert_not_called()
