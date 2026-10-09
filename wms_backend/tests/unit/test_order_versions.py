"""Focused tests for append-only order versions and snapshot reconstruction."""

import json
from unittest.mock import patch

import pytest

from data.DB import CargoTable, OrderTable, cargo_model, order_model
from data.order_version import (
    OrderVersionTable,
    change_to_dict,
    ensure_baseline,
    get_version_detail,
    reconstruct_snapshot,
    snapshot_order,
)
from data.packing import box_model
from data.packing.PackingList import PackingListTable
from data.user.User import UserTable


NOW = "2026-09-16 09:00:00"


@pytest.fixture(autouse=True)
def _use_test_session_for_history_queries(setup_test_database):
    """Keep history read helpers on the per-test in-memory SQLite connection."""
    with patch(
        "data.order_version.SessionFactory", return_value=setup_test_database
    ):
        yield


def _seed_order(session, uid="version-order", *, receiver="初始收件人"):
    order = OrderTable(
        uid=uid,
        order_id="VERSION-001",
        customer_name="版本测试客户",
        receiver=receiver,
        archive=False,
        cargo_count=0,
        create_date=NOW,
    )
    session.add(order)
    session.commit()
    return order


def _seed_order_with_cargo(session, *, waybill_id="A"):
    order = _seed_order(session)
    cargo = CargoTable(
        uid="version-cargo",
        origin_id="VERSION-001-1",
        target_order_uid=order.uid,
        transfer_id="ORIGINAL-001",
        waybill_id=waybill_id,
        count=1,
        weight=1.5,
        status=0,
        archive=False,
        create_date=NOW,
    )
    session.add(cargo)
    session.flush()
    ensure_baseline(session, order.uid, snapshot_order(session, order.uid))
    session.commit()
    return order, cargo


def _seed_order_with_box(session, item_details):
    operator = UserTable(
        phone="13890001001",
        name="版本测试操作员",
        password="unused",
        status="approved",
    )
    order = OrderTable(
        uid="version-box-order",
        order_id="VERSION-BOX-001",
        customer_name="箱明细测试客户",
        archive=False,
        cargo_count=1,
        create_date=NOW,
    )
    packing_list = PackingListTable(
        uid="version-packing-list",
        list_number="VERSION-MARK-001",
        creator=operator,
        status="completed",
        archive=False,
        create_date=NOW,
    )
    box = CargoTable(
        uid="version-box",
        origin_id="VERSION-BOX-001",
        tag="VERSION-MARK-001_1",
        target_order_uid=order.uid,
        packing_list_uid=packing_list.uid,
        item_name="旧品名",
        real_en_name="旧品名",
        item_details=json.dumps(item_details, ensure_ascii=False),
        count=sum(row["piece_count"] for row in item_details),
        piece_count=sum(row["piece_count"] for row in item_details),
        box_number=1,
        weight=2.5,
        status=0,
        archive=False,
        create_date=NOW,
    )
    session.add_all([operator, order, packing_list, box])
    session.flush()
    ensure_baseline(session, order.uid, snapshot_order(session, order.uid))
    session.commit()
    return order, box


def _version_rows(session, order_uid):
    return (
        session.query(OrderVersionTable)
        .filter(OrderVersionTable.order_uid == order_uid)
        .order_by(OrderVersionTable.version_no.asc())
        .all()
    )


def test_new_order_creates_complete_v1(setup_test_database):
    session = setup_test_database

    uid = order_model.create(
        {
            "order_id": "CREATED-V1",
            "customer_name": "新订单客户",
            "receiver": "新订单收件人",
            "cargo_count": 0,
            "archive": False,
        }
    )

    versions = _version_rows(session, uid)
    assert [(row.version_no, row.action) for row in versions] == [
        (1, "order_created")
    ]
    snapshot, _ = reconstruct_snapshot(session, uid, 1)
    assert snapshot["order"]["uid"] == uid
    assert snapshot["order"]["order_id"] == "CREATED-V1"
    assert snapshot["order"]["receiver"] == "新订单收件人"
    assert snapshot["cargos"] == []
    assert snapshot["boxes"] == []


def test_missing_baseline_is_seeded_before_first_increment(setup_test_database):
    session = setup_test_database
    order = _seed_order(session, receiver="旧地址")
    order_uid = order.uid

    order_model.update(order_uid, {"receiver": "新地址"})

    versions = _version_rows(session, order_uid)
    assert [(row.version_no, row.action) for row in versions] == [
        (1, "baseline_import"),
        (2, "order_updated"),
    ]
    v1, _ = reconstruct_snapshot(session, order_uid, 1)
    v2, _ = reconstruct_snapshot(session, order_uid, 2)
    assert v1["order"]["receiver"] == "旧地址"
    assert v2["order"]["receiver"] == "新地址"


def test_item_details_are_recorded_as_whole_before_and_after_lists(
    setup_test_database,
):
    session = setup_test_database
    before_details = [
        {"item_name": "衣服", "customs_code": "6101", "piece_count": 2},
        {"item_name": "鞋子", "customs_code": "6401", "piece_count": 1},
    ]
    after_details = [
        {"item_name": "衣服", "customs_code": "6101", "piece_count": 3},
        {"item_name": "帽子", "customs_code": "6505", "piece_count": 2},
    ]
    order, box = _seed_order_with_box(session, before_details)
    order_uid = order.uid
    box_uid = box.uid

    assert box_model.update(box_uid, {"item_details": after_details}) is True

    version = _version_rows(session, order_uid)[-1]
    box_change = next(
        change_to_dict(change)
        for change in version.changes
        if change.entity_type == "box" and change.entity_uid == box_uid
    )
    assert box_change["before_data"]["item_details"] == before_details
    assert box_change["after_data"]["item_details"] == after_details
    assert isinstance(box_change["before_data"]["item_details"], list)
    assert isinstance(box_change["after_data"]["item_details"], list)


def test_box_content_and_workers_are_saved_as_one_version(setup_test_database):
    session = setup_test_database
    order, box = _seed_order_with_box(
        session,
        [{"item_name": "衣服", "customs_code": "6101", "piece_count": 2}],
    )
    worker = session.query(UserTable).filter_by(phone="13890001001").one()
    order_uid = order.uid
    box_uid = box.uid
    worker_id = worker.id
    worker_name = worker.name

    assert box_model.update(
        box_uid,
        {"remark": "合并保存", "worker_ids": [worker_id]},
    ) is True

    versions = _version_rows(session, order_uid)
    assert [row.version_no for row in versions] == [1, 2]
    changes = [
        change_to_dict(change)
        for change in versions[-1].changes
        if change.entity_type == "box" and change.entity_uid == box_uid
    ]
    assert len(changes) == 1
    assert changes[0]["after_data"]["remark"] == "合并保存"
    assert changes[0]["after_data"]["workers"] == [
        {"worker_id": worker_id, "worker_name": worker_name}
    ]


def test_waybill_a_to_b_to_c_reconstructs_each_version_and_noop_is_skipped(
    setup_test_database,
):
    session = setup_test_database
    order, cargo = _seed_order_with_cargo(session, waybill_id="A")
    order_uid = order.uid
    cargo_uid = cargo.uid

    cargo_model.update(cargo_uid, {"waybill_id": "B"})
    cargo_model.update(cargo_uid, {"waybill_id": "C"})
    cargo_model.update(cargo_uid, {"waybill_id": "C"})

    versions = _version_rows(session, order_uid)
    assert [row.version_no for row in versions] == [1, 2, 3]
    assert len(versions) == 3
    for version_no, expected in ((1, "A"), (2, "B"), (3, "C")):
        snapshot, _ = reconstruct_snapshot(session, order_uid, version_no)
        assert snapshot["cargos"][0]["waybill_id"] == expected

    second_change = next(
        change_to_dict(change)
        for change in versions[1].changes
        if change.entity_uid == cargo_uid
    )
    third_change = next(
        change_to_dict(change)
        for change in versions[2].changes
        if change.entity_uid == cargo_uid
    )
    assert second_change["before_data"] == {"waybill_id": "A"}
    assert second_change["after_data"] == {"waybill_id": "B"}
    assert third_change["before_data"] == {"waybill_id": "B"}
    assert third_change["after_data"] == {"waybill_id": "C"}


def test_version_write_failure_rolls_back_business_change(setup_test_database):
    session = setup_test_database
    order, cargo = _seed_order_with_cargo(session, waybill_id="A")
    order_uid = order.uid
    cargo_uid = cargo.uid

    with patch(
        "data.order_version.append_version",
        side_effect=RuntimeError("version insert failed"),
    ):
        with pytest.raises(RuntimeError, match="version insert failed"):
            cargo_model.update(cargo_uid, {"waybill_id": "B"})

    session.expire_all()
    persisted = session.query(CargoTable).filter_by(uid=cargo_uid).one()
    assert persisted.waybill_id == "A"
    assert len(_version_rows(session, order_uid)) == 1


def test_hard_delete_keeps_tombstone_and_last_existing_snapshot(setup_test_database):
    session = setup_test_database
    order = _seed_order(session, uid="deleted-version-order")
    order_uid = order.uid
    ensure_baseline(session, order_uid, snapshot_order(session, order_uid))
    session.commit()

    order_model.delete(order_uid)

    assert session.query(OrderTable).filter_by(uid=order_uid).first() is None
    versions = _version_rows(session, order_uid)
    assert [(row.version_no, row.action, bool(row.deleted)) for row in versions] == [
        (1, "baseline_import", False),
        (2, "order_deleted", True),
    ]
    detail = get_version_detail(order_uid, 2)
    assert detail["snapshot"]["deleted"] is True
    assert detail["snapshot"]["order"] is None
    assert detail["last_existing_snapshot"]["order"]["order_id"] == "VERSION-001"
