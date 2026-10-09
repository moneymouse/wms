"""Imports commit per order, report failed items, and keep shipment facts stable."""

from io import BytesIO

import pytest

from data import cargo_model
from data.DB import BoxCostRecordTable, CargoOutboundRecordTable, CargoTable, OrderTable
from data.customer.Customer import CustomerTable
from data.order_version import OrderVersionChangeTable, OrderVersionTable
from data.packing.PackingList import PackingListTable
from services.cargo_service import apply_waybill_table
from services.outbound_service import WaybillImportResult, update_waybill_table


ADMIN = {"user_id": 1, "name": "管理员", "role": "admin"}
ORIGINAL_NUMBER = "8288399733"
ORDER_NUMBER = "8288399738"
INVALID_ORIGINAL_NUMBER = "8288399744"
OTHER_ORDER_NUMBER = "BAD-ORDER"


def _configure_example(world, mark="MARK", *, mismatched_box=False,
                       separate_order=False, invalid_uid="z-invalid-box",
                       include_valid_sibling=False):
    with world["factory"]() as session:
        box = session.get(CargoTable, "box")
        box.transfer_id = ORIGINAL_NUMBER
        box.box_number = 4
        box.tag = f"{mark}_4"
        session.get(OrderTable, "order").order_id = ORDER_NUMBER
        session.get(PackingListTable, "packing").list_number = mark
        if mismatched_box:
            session.add(CustomerTable(id=2, name="另一客户"))
            session.add(PackingListTable(
                uid="other-packing", list_number="OTHER-MARK", customer_id=2,
                creator_id=1, archive=False,
            ))
            order_uid = "other-order" if separate_order else "order"
            if separate_order:
                order = OrderTable(
                    uid=order_uid, order_id=OTHER_ORDER_NUMBER,
                    transportation="渠道", archive=False,
                )
                order.customers = [session.get(CustomerTable, 1)]
                session.add(order)
            session.add(CargoTable(
                uid=invalid_uid, packing_list_uid="other-packing",
                target_order_uid=order_uid, transfer_id=INVALID_ORIGINAL_NUMBER,
                box_number=5, tag="OTHER-MARK_5", waybill_id="", status=0,
                weight=3, piece_count=1, archive=False,
            ))
            if include_valid_sibling:
                # This sibling sorts before the bad box within its order.
                session.add(CargoTable(
                    uid="y-other-valid-box", packing_list_uid="packing",
                    target_order_uid=order_uid, transfer_id="SIBLING-ORIGINAL",
                    box_number=6, tag=f"{mark}_6", waybill_id="", status=0,
                    weight=4, piece_count=1, archive=False,
                ))
        session.commit()


def _state(world, order_uid=None):
    with world["factory"]() as session:
        query = session.query(CargoTable)
        if order_uid:
            query = query.filter_by(target_order_uid=order_uid)
        cargos = {
            row.uid: (row.status, row.date, row.waybill_id, row.weight, row.update_date)
            for row in query.order_by(CargoTable.uid)
        }
        queries = [session.query(table) for table in (
            BoxCostRecordTable, CargoOutboundRecordTable, OrderVersionTable,
        )]
        changes = session.query(OrderVersionChangeTable)
        if order_uid:
            queries = [query.filter_by(order_uid=order_uid) for query in queries]
            changes = changes.join(OrderVersionTable).filter(OrderVersionTable.order_uid == order_uid)
        history_counts = tuple(query.count() for query in [*queries, changes])
        return cargos, history_counts


def _upload(world, headers, transfer_map):
    contents = "".join(f"{original},{waybill}\n" for original, waybill in transfer_map.items())
    return world["client"].post(
        "/api/order/upload/transfer_table",
        headers={"x-token": headers["x-token"]},
        data={"filename": "waybills.txt", "file": (BytesIO(contents.encode()), "waybills.txt")},
    )


def _assert_mismatch_details(message, *, original, mark, box_number, order_number=ORDER_NUMBER):
    assert "箱子与订单的客户归属不一致" in message
    for detail in (
        f"原单号：{original}", f"装箱单：{mark}", f"箱号：{box_number}",
        f"订单号：{order_number}", "装箱单客户ID：2", "订单客户ID：1",
    ):
        assert detail in message


@pytest.mark.parametrize("mark", ["MARK", "SECK"])
def test_matching_customer_import_accepts_example_original_number(world, mark):
    _configure_example(world, mark)

    registered, error = apply_waybill_table(
        cargo_model, {ORIGINAL_NUMBER: "WB-EXAMPLE"}, operator=ADMIN,
    )

    assert error is None
    assert registered == [("box", "WB-EXAMPLE")]
    with world["factory"]() as session:
        box = session.get(CargoTable, "box")
        assert (box.transfer_id, box.box_number, box.waybill_id, box.status) == (
            ORIGINAL_NUMBER, 4, "WB-EXAMPLE", 1,
        )
        assert box.date
        cost = session.query(BoxCostRecordTable).one()
        assert (cost.box_uid, cost.waybill_id, cost.total_cost) == ("box", "WB-EXAMPLE", 6)
        event = session.query(CargoOutboundRecordTable).one()
        assert (event.cargo_uid, event.source) == ("box", "waybill_import")
        assert session.query(OrderVersionTable).count() == 2


def test_later_customer_mismatch_rolls_back_all_items_of_same_order(world, headers):
    _configure_example(world, mismatched_box=True)
    before = _state(world)

    response = _upload(world, headers, {
        ORIGINAL_NUMBER: "WB-VALID", INVALID_ORIGINAL_NUMBER: "WB-INVALID",
    })

    assert response.status_code == 400, response.get_json()
    body = response.get_json()
    assert body["code"] == 400 and body["cargo_count"] == 0
    assert body["success_list"] == body["success_items"] == []
    assert {item["uid"] for item in body["failed_list"]} == {"box", "z-invalid-box"}
    _assert_mismatch_details(
        next(item["reason"] for item in body["failed_list"] if item["uid"] == "z-invalid-box"),
        original=INVALID_ORIGINAL_NUMBER,
        mark="OTHER-MARK", box_number=5,
    )
    assert _state(world) == before


def test_other_order_mismatch_does_not_undo_valid_manual_save_or_number_correction(world, headers):
    _configure_example(world, mismatched_box=True, separate_order=True)
    response = world["client"].put(
        "/api/box/box", headers=headers, json={"waybill_id": "WB-MANUAL"},
    )
    assert response.status_code == 200, response.get_json()
    before_upload = _state(world, "order")
    assert before_upload[0]["box"][0] == 1
    assert before_upload[0]["box"][2] == "WB-MANUAL"

    response = _upload(world, headers, {
        ORIGINAL_NUMBER: "WB-CORRECTION", INVALID_ORIGINAL_NUMBER: "WB-INVALID",
    })

    assert response.status_code == 200, response.get_json()
    body = response.get_json()
    assert body["code"] == 207 and body["cargo_count"] == 1
    assert body["success_list"] == [["box", "WB-CORRECTION"]]
    assert [item["uid"] for item in body["failed_list"]] == ["z-invalid-box"]
    _assert_mismatch_details(
        body["failed_list"][0]["reason"], original=INVALID_ORIGINAL_NUMBER,
        mark="OTHER-MARK", box_number=5, order_number=OTHER_ORDER_NUMBER,
    )
    after_upload = _state(world, "order")
    assert after_upload[0]["box"][0] == 1
    assert after_upload[0]["box"][1] == before_upload[0]["box"][1]
    assert after_upload[0]["box"][2] == "WB-CORRECTION"
    assert after_upload[1][:2] == before_upload[1][:2] == (1, 1)
    assert _state(world, "other-order")[0]["z-invalid-box"][:3] == (0, None, "")


def test_real_customer_mismatch_is_also_blocked_for_manual_save(world, headers):
    _configure_example(world, mismatched_box=True)
    before = _state(world)

    response = world["client"].put(
        "/api/box/z-invalid-box", headers=headers, json={"waybill_id": "WB-MANUAL"},
    )

    assert response.status_code == 400, response.get_json()
    _assert_mismatch_details(
        response.get_json()["msg"], original=INVALID_ORIGINAL_NUMBER,
        mark="OTHER-MARK", box_number=5,
    )
    assert _state(world) == before


def test_successful_order_commits_and_failed_order_rolls_back_all_its_boxes(world, headers, monkeypatch):
    _configure_example(
        world, mismatched_box=True, separate_order=True, include_valid_sibling=True,
    )
    before_failed_order = _state(world, "other-order")
    tracked = []
    monkeypatch.setattr("services.cargo_service.registerTrack", lambda pairs: tracked.append(pairs))

    response = _upload(world, headers, {
        ORIGINAL_NUMBER: "WB-VALID", "SIBLING-ORIGINAL": "WB-SIBLING",
        INVALID_ORIGINAL_NUMBER: "WB-INVALID",
    })

    assert response.status_code == 200, response.get_json()
    body = response.get_json()
    assert body["code"] == 207 and body["cargo_count"] == 1
    assert body["success_list"] == [["box", "WB-VALID"]]
    assert body["success_items"] == [{
        "uid": "box", "order_uid": "order", "order_id": ORDER_NUMBER,
        "transfer_id": ORIGINAL_NUMBER, "waybill_id": "WB-VALID",
    }]
    assert body["tracking_error"] is None
    failures = {item["uid"]: item for item in body["failed_list"]}
    assert set(failures) == {"y-other-valid-box", "z-invalid-box"}
    assert all(item["code"] == 400 and item["order_uid"] == "other-order" for item in failures.values())
    failed = failures["z-invalid-box"]
    assert (failed["order_id"], failed["transfer_id"], failed["waybill_id"]) == (
        OTHER_ORDER_NUMBER, INVALID_ORIGINAL_NUMBER, "WB-INVALID",
    )
    _assert_mismatch_details(
        failed["reason"], original=INVALID_ORIGINAL_NUMBER, mark="OTHER-MARK",
        box_number=5, order_number=OTHER_ORDER_NUMBER,
    )
    assert _state(world, "other-order") == before_failed_order
    successful_rows, successful_history = _state(world, "order")
    assert successful_rows["box"][0] == 1 and successful_rows["box"][2] == "WB-VALID"
    assert successful_history[:3] == (1, 1, 2)
    assert tracked == [[("box", "WB-VALID")]]


@pytest.mark.parametrize("with_failed_order", [False, True])
def test_retry_counts_unchanged_success_without_duplicate_history_or_tracking(
    world, headers, monkeypatch, with_failed_order,
):
    _configure_example(world, mismatched_box=with_failed_order, separate_order=with_failed_order)
    transfer_map = {ORIGINAL_NUMBER: "WB-VALID"}
    if with_failed_order:
        transfer_map[INVALID_ORIGINAL_NUMBER] = "WB-INVALID"
    tracked = []
    monkeypatch.setattr("services.cargo_service.registerTrack", lambda pairs: tracked.append(pairs))
    first = _upload(world, headers, transfer_map)
    assert first.status_code == 200, first.get_json()
    before_retry = _state(world)

    response = _upload(world, headers, transfer_map)

    assert response.status_code == 200, response.get_json()
    body = response.get_json()
    assert body["code"] == (207 if with_failed_order else 200)
    assert body["cargo_count"] == 1 and body["success_list"] == [["box", "WB-VALID"]]
    assert body["success_items"][0]["transfer_id"] == ORIGINAL_NUMBER
    assert len(body["failed_list"]) == int(with_failed_order)
    assert tracked == [[("box", "WB-VALID")]]
    assert _state(world) == before_retry


@pytest.mark.parametrize("tracking_code", [500, 502])
def test_tracking_failure_preserves_successful_order_and_business_failure_items(
    world, headers, monkeypatch, tracking_code,
):
    _configure_example(world, mismatched_box=True, separate_order=True)
    before_failed_order = _state(world, "other-order")

    def fail_tracking(pairs):
        assert pairs == [("box", "WB-VALID")]
        assert _state(world, "order")[0]["box"][0] == 1
        if tracking_code == 502:
            raise RuntimeError({"code": 502, "data": ["WB-VALID"]})
        raise RuntimeError("tracking unavailable")

    monkeypatch.setattr("services.cargo_service.registerTrack", fail_tracking)
    response = _upload(world, headers, {
        ORIGINAL_NUMBER: "WB-VALID", INVALID_ORIGINAL_NUMBER: "WB-INVALID",
    })

    assert response.status_code == 200, response.get_json()
    body = response.get_json()
    assert body["code"] == tracking_code and body["cargo_count"] == 1
    assert body["tracking_error"] == {
        "code": tracking_code,
        "reason": "17track rejected" if tracking_code == 502 else "Register Error",
    }
    assert body["success_list"] == [["box", "WB-VALID"]]
    assert len(body["failed_list"]) == 1 and body["failed_list"][0]["code"] == 400
    assert "客户归属不一致" in body["failed_list"][0]["reason"]
    assert _state(world, "other-order") == before_failed_order
    assert _state(world, "order")[1][:2] == (1, 1)


@pytest.mark.parametrize("invalid_uid", ["a-invalid-box", "z-invalid-box"])
@pytest.mark.parametrize("failure_type", ["runtime", "database"])
def test_order_failure_does_not_block_earlier_or_later_successful_order(
    world, monkeypatch, invalid_uid, failure_type,
):
    from sqlalchemy.exc import IntegrityError
    from services import outbound_service

    _configure_example(world, mismatched_box=True, separate_order=True, invalid_uid=invalid_uid)
    # Make the second order valid so the injected failure occurs after its writes.
    with world["factory"]() as session:
        session.get(PackingListTable, "other-packing").customer_id = 1
        session.commit()
    before_failed_order = _state(world, "other-order")
    record_mutation = outbound_service.record_mutation

    def fail_one_order(session, order_uid, **kwargs):
        if order_uid == "other-order":
            if failure_type == "database":
                raise IntegrityError("test insert", {}, RuntimeError("test constraint failure"))
            raise RuntimeError("test order mutation failure")
        return record_mutation(session, order_uid, **kwargs)

    monkeypatch.setattr(outbound_service, "record_mutation", fail_one_order)
    result, error = apply_waybill_table(
        cargo_model, {ORIGINAL_NUMBER: "WB-VALID", INVALID_ORIGINAL_NUMBER: "WB-OTHER"},
        operator=ADMIN, return_details=True,
    )

    assert isinstance(result, WaybillImportResult) and error is None
    assert result.registered == [("box", "WB-VALID")]
    assert [item["uid"] for item in result.successful] == ["box"]
    assert len(result.failed) == 1 and result.failed[0]["uid"] == invalid_uid
    assert result.failed[0]["code"] == 500
    assert _state(world, "other-order") == before_failed_order
    assert _state(world, "order")[0]["box"][0] == 1
    assert _state(world, "order")[1][:3] == (1, 1, 2)


@pytest.mark.parametrize("original,waybill,code,reason", [
    ("MISSING-ORIGINAL", "WB-MISSING", 404, "未找到"),
    (ORIGINAL_NUMBER, "", 400, "转单号未填写"),
    (ORIGINAL_NUMBER, "   ", 400, "转单号未填写"),
    ("", "WB-NO-ORIGINAL", 400, "原单号未填写"),
])
def test_invalid_import_item_is_reported_instead_of_disappearing(
    world, headers, monkeypatch, original, waybill, code, reason,
):
    _configure_example(world)
    before = _state(world)
    tracked = []
    monkeypatch.setattr("services.cargo_service.registerTrack", lambda pairs: tracked.append(pairs))

    response = _upload(world, headers, {original: waybill})

    assert response.status_code == 400, response.get_json()
    body = response.get_json()
    assert body["code"] == 400 and body["cargo_count"] == 0
    assert body["success_list"] == body["success_items"] == []
    assert len(body["failed_list"]) == 1
    failed = body["failed_list"][0]
    assert (failed["transfer_id"], failed["waybill_id"], failed["code"]) == (original, waybill.strip(), code)
    assert reason in failed["reason"]
    if original != ORIGINAL_NUMBER:
        assert failed["uid"] is None and failed["order_uid"] is None
    assert _state(world) == before and tracked == []


def test_missing_original_can_fail_while_matched_order_commits(world, headers):
    _configure_example(world)
    response = _upload(world, headers, {ORIGINAL_NUMBER: "WB-VALID", "MISSING": "WB-MISSING"})
    assert response.status_code == 200, response.get_json()
    body = response.get_json()
    assert body["code"] == 207 and body["cargo_count"] == 1
    assert body["success_list"] == [["box", "WB-VALID"]]
    assert len(body["failed_list"]) == 1 and body["failed_list"][0]["code"] == 404
    assert body["failed_list"][0]["transfer_id"] == "MISSING"
    assert _state(world, "order")[0]["box"][0] == 1


def test_empty_waybill_rolls_back_other_import_items_of_same_order(world, headers):
    _configure_example(world)
    before = _state(world)
    response = _upload(world, headers, {ORIGINAL_NUMBER: "", "ORIG-CARGO": "WB-CARGO"})
    assert response.status_code == 400, response.get_json()
    body = response.get_json()
    assert body["cargo_count"] == 0 and not body["success_items"]
    assert {item["uid"] for item in body["failed_list"]} == {"box", "cargo"}
    assert all(item["code"] == 400 and "转单号未填写" in item["reason"] for item in body["failed_list"])
    assert _state(world) == before


@pytest.mark.parametrize("shared_number", ["original", "waybill"])
def test_repeated_number_keeps_success_and_failure_for_distinct_cargo(world, headers, shared_number):
    _configure_example(world, mismatched_box=True, separate_order=True)
    transfer_map = {ORIGINAL_NUMBER: "WB-SHARED", INVALID_ORIGINAL_NUMBER: "WB-SHARED"}
    if shared_number == "original":
        with world["factory"]() as session:
            session.get(CargoTable, "z-invalid-box").transfer_id = ORIGINAL_NUMBER
            session.commit()
        transfer_map = {ORIGINAL_NUMBER: "WB-SHARED"}

    response = _upload(world, headers, transfer_map)

    assert response.status_code == 200, response.get_json()
    body = response.get_json()
    assert body["code"] == 207 and body["cargo_count"] == 1
    assert body["success_list"] == [["box", "WB-SHARED"]]
    assert [item["uid"] for item in body["success_items"]] == ["box"]
    assert [item["uid"] for item in body["failed_list"]] == ["z-invalid-box"]
    assert body["failed_list"][0]["transfer_id"] == (
        ORIGINAL_NUMBER if shared_number == "original" else INVALID_ORIGINAL_NUMBER
    )
    assert _state(world, "order")[0]["box"][2] == "WB-SHARED"
    assert _state(world, "other-order")[0]["z-invalid-box"][:3] == (0, None, "")


def test_default_service_result_contains_only_committed_changed_pairs(world):
    _configure_example(world, mismatched_box=True, separate_order=True)
    assert update_waybill_table(
        world["factory"], {ORIGINAL_NUMBER: "WB-VALID", INVALID_ORIGINAL_NUMBER: "WB-INVALID"},
        operator=ADMIN,
    ) == [("box", "WB-VALID")]
    assert update_waybill_table(
        world["factory"], {ORIGINAL_NUMBER: "WB-VALID", INVALID_ORIGINAL_NUMBER: "WB-INVALID"},
        operator=ADMIN,
    ) == []
