"""Number allocation, collision protection, permissions and atomic persistence."""

import itertools
import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from Auth import create_jwt
from data import cargo_model, order_model
from data.DB import BoxCostRecordTable, CargoOutboundRecordTable, CargoTable, OrderTable
from data.order_version import OrderVersionChangeTable, OrderVersionTable
from data.packing.PackingList import PackingListTable
from services import number_generation_service
from services.order_edit_policy import ORIGINAL_NUMBER_IMMUTABLE_MESSAGE
from services.outbound_service import confirm_outbound, undo_outbound


ACTOR = {"user_id": 1, "name": "操作员", "role": "clerk"}
ORDER_ROUTE = "/api/orders/order/generate-order-number"
BOX_ROUTE = "/api/orders/order/cargo/box/generate-original-number"
PACKING_ROUTE = "/api/packing-lists/packing/boxes/generate-original-numbers"


def formatted(number, field):
    return f"D{number}L"


def headers(role="clerk", **payload):
    return {"x-token": create_jwt({**ACTOR, "role": role, **payload})}


def rows(world):
    """Capture all business columns so accidental shipment changes are visible."""
    with world["factory"]() as session:
        return {
            model.__tablename__: {
                row.uid: {column.name: getattr(row, column.name)
                          for column in model.__table__.columns}
                for row in session.query(model).order_by(model.uid)
            }
            for model in (OrderTable, CargoTable)
        }


def versions(world):
    with world["factory"]() as session:
        return [(row.id, row.order_uid, row.version_no, row.action)
                for row in session.query(OrderVersionTable).order_by(OrderVersionTable.id)]


def assert_only_number_changed(before, after, table, uid, field, number):
    expected = {name: {key: dict(value) for key, value in entities.items()}
                for name, entities in before.items()}
    expected[table][uid][field] = number
    # Mutation timestamps are audit metadata rather than shipment occurrence.
    expected[table][uid]["update_date"] = after[table][uid]["update_date"]
    assert after == expected


@pytest.mark.parametrize("route, field, table, uid", [
    (ORDER_ROUTE, "order_id", "orders", "order"),
    (BOX_ROUTE, "transfer_id", "cargos", "box"),
])
@pytest.mark.parametrize("random_value, expected", [(0, "800000000"), (99_999_999, "899999999")])
def test_click_allocates_d_l_number_with_nine_digits_and_changes_only_the_target(
    world, monkeypatch, route, field, table, uid, random_value, expected,
):
    expected = formatted(expected, field)
    random = Mock(return_value=random_value)
    monkeypatch.setattr(number_generation_service.secrets, "randbelow", random)
    before = rows(world)

    # Viewing the existing detail must not allocate or persist a number.
    response = world["client"].get("/api/orders/order", headers=headers())
    assert response.status_code == 200, response.json
    assert rows(world) == before
    random.assert_not_called()

    response = world["client"].post(route, headers=headers(), json={})

    assert response.status_code == 200, response.json
    assert response.json["code"] == 200
    assert response.json["data"][field] == expected
    assert re.fullmatch(r"D8\d{8}L", expected)
    assert len(expected) == 11
    random.assert_called_once_with(100_000_000)
    assert_only_number_changed(before, rows(world), table, uid, field, expected)
    with world["factory"]() as session:
        assert session.query(CargoOutboundRecordTable).count() == 0
        assert session.query(BoxCostRecordTable).count() == 0


@pytest.mark.parametrize("route, field", [(ORDER_ROUTE, "order_id"), (BOX_ROUTE, "transfer_id")])
def test_allocation_checks_both_tables_including_archived_records(world, monkeypatch, route, field):
    with world["factory"].begin() as session:
        session.add_all([
            OrderTable(uid="archived-order", order_id=formatted("800000011", field), archive=True),
            CargoTable(uid="archived-cargo", transfer_id=formatted("800000012", field), archive=True),
            CargoTable(uid="active-collision", transfer_id=formatted("800000013", field), archive=False),
            OrderTable(uid="active-order-collision", order_id=formatted("800000014", field), archive=False),
        ])
    random = Mock(side_effect=[11, 12, 13, 14, 15])
    monkeypatch.setattr(number_generation_service.secrets, "randbelow", random)

    response = world["client"].post(route, headers=headers(), json={})

    assert response.status_code == 200, response.json
    assert response.json["data"][field] == formatted("800000015", field)
    assert random.call_count == 5


@pytest.mark.parametrize("role", ["admin", "store_manager", "salesperson", "clerk"])
@pytest.mark.parametrize("route", [ORDER_ROUTE, BOX_ROUTE])
def test_authorized_roles_can_generate(world, role, route):
    response = world["client"].post(route, headers=headers(role), json={})
    assert response.status_code == 200, response.json


@pytest.mark.parametrize("role", ["employee", "worker", "finance", "customer"])
@pytest.mark.parametrize("route", [ORDER_ROUTE, BOX_ROUTE])
def test_other_roles_cannot_generate_and_leave_no_history(world, monkeypatch, role, route):
    random = Mock()
    monkeypatch.setattr(number_generation_service.secrets, "randbelow", random)
    before = rows(world)
    response = world["client"].post(route, headers=headers(role), json={})
    assert response.status_code == 403, response.json
    assert rows(world) == before
    assert versions(world) == []
    random.assert_not_called()


@pytest.mark.parametrize("route", [ORDER_ROUTE, BOX_ROUTE])
def test_multirole_token_uses_allowed_secondary_role(world, route):
    response = world["client"].post(
        route, headers=headers("employee", roles=["employee", "clerk"]), json={},
    )
    assert response.status_code == 200, response.json


@pytest.mark.parametrize("route", [ORDER_ROUTE, BOX_ROUTE])
def test_generation_requires_authentication(world, route):
    before = rows(world)
    response = world["client"].post(route, json={})
    assert response.status_code == 401, response.json
    assert rows(world) == before
    assert versions(world) == []


@pytest.mark.parametrize("route, status", [
    ("/api/orders/missing/generate-order-number", 404),
    ("/api/orders/missing/cargo/box/generate-original-number", 404),
    ("/api/orders/order/cargo/missing/generate-original-number", 404),
    ("/api/orders/order/cargo/other-cargo/generate-original-number", 409),
])
def test_missing_order_or_nonmember_cargo_cannot_generate(world, route, status):
    before = rows(world)
    response = world["client"].post(route, headers=headers(), json={})
    assert response.status_code == status, response.json
    assert rows(world) == before
    assert versions(world) == []


@pytest.mark.parametrize("archive_target", ["order", "box"])
def test_archived_target_cannot_generate(world, archive_target):
    with world["factory"].begin() as session:
        model = OrderTable if archive_target == "order" else CargoTable
        session.get(model, archive_target).archive = True
    before = rows(world)
    routes = [ORDER_ROUTE, BOX_ROUTE] if archive_target == "order" else [BOX_ROUTE]
    for route in routes:
        response = world["client"].post(route, headers=headers(), json={})
        assert response.status_code in (404, 409), response.json
    assert rows(world) == before
    assert versions(world) == []


def test_box_in_archived_packing_list_cannot_generate(world):
    with world["factory"].begin() as session:
        session.get(PackingListTable, "packing").archive = True
    before = rows(world)
    response = world["client"].post(BOX_ROUTE, headers=headers(), json={})
    assert response.status_code == 409, response.json
    assert rows(world) == before
    assert versions(world) == []


@pytest.mark.parametrize("evidence", ["status", "date"])
def test_box_original_number_is_protected_while_currently_outbound(world, evidence):
    with world["factory"].begin() as session:
        box = session.get(CargoTable, "box")
        if evidence == "status":
            box.status = 1
        elif evidence == "date":
            box.date = "2026-10-01 10:00:00"
    before = rows(world)

    response = world["client"].post(BOX_ROUTE, headers=headers(), json={})

    assert response.status_code == 409, response.json
    assert response.json["msg"] == ORIGINAL_NUMBER_IMMUTABLE_MESSAGE
    assert rows(world) == before
    assert versions(world) == []


def test_box_reentry_allows_generation_and_preserves_shipment_history(world, monkeypatch):
    actor = {**ACTOR, "role": "admin"}
    confirm_outbound(["box"], operator=actor)
    undo_outbound("box", operator=actor)
    before = rows(world)
    monkeypatch.setattr(number_generation_service.secrets, "randbelow", lambda upper: 42)

    response = world["client"].post(
        BOX_ROUTE, headers=headers(), json={"expected_value": "8234567890"},
    )

    assert response.status_code == 200, response.json
    assert_only_number_changed(before, rows(world), "cargos", "box", "transfer_id", "D800000042L")
    assert versions(world)[-1][3] == "original_number_generated"
    with world["factory"]() as session:
        assert session.query(CargoOutboundRecordTable).count() == 1
        assert session.query(BoxCostRecordTable).filter_by(archive=False).count() == 0
        assert session.query(BoxCostRecordTable).filter_by(archive=True).count() == 1
        assert session.get(CargoTable, "box").box_number == 1


def test_ordinary_outbound_cargo_keeps_original_number_editable(world):
    with world["factory"].begin() as session:
        cargo = session.get(CargoTable, "cargo")
        cargo.status = 1
        cargo.date = "2026-10-01 10:00:00"
    before = rows(world)
    response = world["client"].post(
        "/api/orders/order/cargo/cargo/generate-original-number", headers=headers(), json={},
    )
    assert response.status_code == 200, response.json
    assert_only_number_changed(
        before, rows(world), "cargos", "cargo", "transfer_id", response.json["data"]["transfer_id"],
    )


@pytest.mark.parametrize("route, current_value, field", [
    (ORDER_ROUTE, "8123456789", "order_id"),
    (BOX_ROUTE, "8234567890", "transfer_id"),
])
def test_expected_value_rejects_stale_click_and_accepts_current_value(
    world, monkeypatch, route, current_value, field,
):
    random = Mock(return_value=123)
    monkeypatch.setattr(number_generation_service.secrets, "randbelow", random)
    before = rows(world)
    response = world["client"].post(route, headers=headers(), json={"expected_value": "stale"})
    assert response.status_code == 409, response.json
    assert rows(world) == before
    assert versions(world) == []
    random.assert_not_called()

    response = world["client"].post(route, headers=headers(), json={"expected_value": current_value})
    assert response.status_code == 200, response.json
    assert response.json["data"][field] == formatted("800000123", field)
    after = rows(world)
    history = versions(world)
    response = world["client"].post(route, headers=headers(), json={"expected_value": current_value})
    assert response.status_code == 409, response.json
    assert rows(world) == after
    assert versions(world) == history


@pytest.mark.parametrize("body", [
    [], "800000123", {"expected_value": 123}, {"order_id": "800000123"},
    {"expected_value": "8123456789", "confirm_outbound": True},
])
@pytest.mark.parametrize("route", [ORDER_ROUTE, BOX_ROUTE])
def test_generation_rejects_malformed_body_and_unrequested_fields(world, route, body):
    before = rows(world)
    response = world["client"].post(route, headers=headers(), json=body)
    assert response.status_code == 400, response.json
    assert rows(world) == before
    assert versions(world) == []


@pytest.mark.parametrize("route, model, uid, field", [
    (ORDER_ROUTE, OrderTable, "order", "order_id"),
    (BOX_ROUTE, CargoTable, "box", "transfer_id"),
])
@pytest.mark.parametrize("saved_value, expected", [(None, None), ("", "")])
def test_empty_number_can_be_generated_with_matching_expected_value(
    world, route, model, uid, field, saved_value, expected,
):
    with world["factory"].begin() as session:
        setattr(session.get(model, uid), field, saved_value)
    response = world["client"].post(route, headers=headers(), json={"expected_value": expected})
    assert response.status_code == 200, response.json
    assert re.fullmatch(r"D8\d{8}L", response.json["data"][field])


def test_manual_numbers_still_accept_duplicates_across_and_within_tables(world):
    repeated = "8123456789"
    order_model.update("other-order", {"order_id": repeated})
    cargo_model.update("cargo", {"transfer_id": repeated})
    cargo_model.update("box", {"transfer_id": repeated})
    with world["factory"]() as session:
        assert session.query(OrderTable).filter_by(order_id=repeated).count() == 2
        assert session.query(CargoTable).filter_by(transfer_id=repeated).count() == 2


def test_new_format_does_not_convert_existing_generated_or_manual_numbers(world, monkeypatch):
    with world["factory"].begin() as session:
        session.get(OrderTable, "order").order_id = "800012345"
        session.get(CargoTable, "box").transfer_id = "XD800012346L"
        session.get(CargoTable, "cargo").transfer_id = "MANUAL-123"
    before = rows(world)
    random = Mock(return_value=42)
    monkeypatch.setattr(number_generation_service.secrets, "randbelow", random)

    viewed = world["client"].get("/api/orders/order", headers=headers())
    assert viewed.status_code == 200, viewed.json
    assert rows(world) == before
    random.assert_not_called()

    generated = world["client"].post(
        ORDER_ROUTE, headers=headers(), json={"expected_value": "800012345"},
    )
    assert generated.status_code == 200, generated.json
    assert_only_number_changed(before, rows(world), "orders", "order", "order_id", "D800000042L")


@pytest.mark.parametrize("route, entity_type, entity_uid, field, previous", [
    (ORDER_ROUTE, "order", "order", "order_id", "8123456789"),
    (BOX_ROUTE, "box", "box", "transfer_id", "8234567890"),
])
def test_generated_number_records_one_target_change_and_actor(
    world, monkeypatch, route, entity_type, entity_uid, field, previous,
):
    monkeypatch.setattr(number_generation_service.secrets, "randbelow", lambda upper: 42)
    response = world["client"].post(route, headers=headers(), json={})
    assert response.status_code == 200, response.json
    with world["factory"]() as session:
        history = session.query(OrderVersionTable).order_by(OrderVersionTable.version_no).all()
        assert [version.version_no for version in history] == [1, 2]
        assert history[0].action == "baseline_import"
        version = history[-1]
        assert (version.operator_id, version.operator_name) == (1, "操作员")
        assert json.loads(version.operator_roles) == ["clerk"]
        assert len(version.changes) == 1
        change = version.changes[0]
        assert (change.entity_type, change.entity_uid) == (entity_type, entity_uid)
        assert json.loads(change.before_data)[field] == previous
        assert json.loads(change.after_data)[field] == formatted("800000042", field)


@pytest.mark.parametrize("route", [ORDER_ROUTE, BOX_ROUTE])
def test_collision_retry_limit_does_not_mutate_number_or_history(world, monkeypatch, route):
    with world["factory"].begin() as session:
        session.add(OrderTable(uid="collision", order_id=formatted("800000007", "transfer_id" if route == BOX_ROUTE else "order_id"), archive=True))
    random = Mock(return_value=7)
    monkeypatch.setattr(number_generation_service.secrets, "randbelow", random)
    before = rows(world)
    response = world["client"].post(route, headers=headers(), json={})
    assert response.status_code in (409, 503), response.json
    assert random.call_count == 100
    assert rows(world) == before
    assert versions(world) == []


@pytest.mark.parametrize("target", ["order", "box"])
def test_version_write_failure_rolls_back_number_and_baseline(world, monkeypatch, target):
    from data import order_version

    original_append = order_version.append_version

    def fail_mutation(session, order_uid, **kwargs):
        if kwargs["action"] != "baseline_import":
            raise RuntimeError("simulated number history failure")
        return original_append(session, order_uid, **kwargs)

    monkeypatch.setattr(order_version, "append_version", fail_mutation)
    monkeypatch.setattr(number_generation_service.secrets, "randbelow", lambda upper: 42)
    before = rows(world)
    with pytest.raises(RuntimeError, match="simulated number history failure"):
        if target == "order":
            number_generation_service.generate_order_number("order", ACTOR)
        else:
            number_generation_service.generate_original_number("order", "box", ACTOR)
    assert rows(world) == before
    assert versions(world) == []
    with world["factory"]() as session:
        assert session.query(OrderVersionChangeTable).count() == 0


def test_concurrent_order_and_box_generation_share_one_collision_pool(world, monkeypatch):
    values = itertools.chain([77, 77, 78], itertools.count(79))
    random_lock = threading.Lock()
    start = threading.Barrier(2)

    def random(upper):
        assert upper == 100_000_000
        with random_lock:
            return next(values)

    monkeypatch.setattr(number_generation_service.secrets, "randbelow", random)

    def generate(target):
        start.wait(timeout=5)
        if target == "order":
            return number_generation_service.generate_order_number("order", ACTOR)
        return number_generation_service.generate_original_number("order", "box", ACTOR)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(generate, target) for target in ("order", "box")]
        results = [future.result(timeout=15) for future in futures]
    assert {result["order_uid"] for result in results} == {"order"}
    with world["factory"]() as session:
        order_number = session.get(OrderTable, "order").order_id
        box_number = session.get(CargoTable, "box").transfer_id
        assert re.fullmatch(r"D8\d{8}L", order_number)
        assert re.fullmatch(r"D8\d{8}L", box_number)
        assert {order_number, box_number} == {"D800000077L", "D800000078L"}
        assert [row.version_no for row in session.query(OrderVersionTable).order_by(
            OrderVersionTable.version_no
        )] == [1, 2, 3]


def test_concurrent_generation_on_different_orders_shares_collision_pool(world, monkeypatch):
    values = itertools.chain([77, 77, 78], itertools.count(79))
    random_lock = threading.Lock()
    start = threading.Barrier(2)

    def random(upper):
        assert upper == 100_000_000
        with random_lock:
            return next(values)

    monkeypatch.setattr(number_generation_service.secrets, "randbelow", random)

    def generate(target):
        start.wait(timeout=5)
        if target == "order":
            return number_generation_service.generate_order_number("order", ACTOR)
        return number_generation_service.generate_original_number("other-order", "other-cargo", ACTOR)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(generate, target) for target in ("order", "cargo")]
        results = [future.result(timeout=15) for future in futures]
    assert {result["order_uid"] for result in results} == {"order", "other-order"}
    with world["factory"]() as session:
        order_number = session.get(OrderTable, "order").order_id
        cargo_number = session.get(CargoTable, "other-cargo").transfer_id
        assert re.fullmatch(r"D8\d{8}L", order_number)
        assert re.fullmatch(r"D8\d{8}L", cargo_number)
        assert {order_number, cargo_number} == {"D800000077L", "D800000078L"}
        for order_uid in ("order", "other-order"):
            assert [row.version_no for row in session.query(OrderVersionTable).filter_by(
                order_uid=order_uid
            ).order_by(OrderVersionTable.version_no)] == [1, 2]


def test_packing_batch_generates_assigned_and_unassigned_boxes_and_only_selected_fields(world, monkeypatch):
    with world["factory"].begin() as session:
        session.add(CargoTable(
            uid="unassigned-box", packing_list_uid="packing", box_number=3,
            target_order_uid=None, transfer_id=None, status=0, archive=False, weight=5,
        ))
        session.get(CargoTable, "second-box").target_order_uid = "other-order"
    before = rows(world)
    random = Mock(side_effect=[42, 42, 43, 44])
    monkeypatch.setattr(number_generation_service.secrets, "randbelow", random)
    selected = ["unassigned-box", "box", "second-box"]

    response = world["client"].post(PACKING_ROUTE, headers=headers(), json={
        "box_uids": selected,
        "expected_values": {uid: before["cargos"][uid]["transfer_id"] for uid in selected},
    })

    assert response.status_code == 200, response.json
    result = response.json["data"]
    assert result["generated_count"] == 3
    assert [box["uid"] for box in result["boxes"]] == selected
    assert {box["transfer_id"] for box in result["boxes"]} == {
        "D800000042L", "D800000043L", "D800000044L",
    }
    assert random.call_count == 4
    after = rows(world)
    for box in result["boxes"]:
        before["cargos"][box["uid"]]["transfer_id"] = box["transfer_id"]
        before["cargos"][box["uid"]]["update_date"] = after["cargos"][box["uid"]]["update_date"]
        if box["order_uid"]:
            assert box["current_version"] == 2
        else:
            assert "current_version" not in box
    assert after == before
    with world["factory"]() as session:
        assert session.query(CargoOutboundRecordTable).count() == 0
        assert session.query(BoxCostRecordTable).count() == 0
        assert session.query(OrderVersionChangeTable).filter_by(operation="update").count() == 2


def test_packing_batch_records_one_version_for_multiple_boxes_in_same_order(world):
    response = world["client"].post(PACKING_ROUTE, headers=headers(), json={
        "box_uids": ["box", "second-box"],
    })
    assert response.status_code == 200, response.json
    assert [box["current_version"] for box in response.json["data"]["boxes"]] == [2, 2]
    with world["factory"]() as session:
        history = session.query(OrderVersionTable).order_by(OrderVersionTable.version_no).all()
        assert len(history) == 2
        assert {change.entity_uid for change in history[-1].changes} == {"box", "second-box"}


@pytest.mark.parametrize("invalid_target", ["outbound", "date", "archived", "other-packing", "stale", "missing", "archived-order", "archived-packing"])
def test_packing_batch_rejects_entire_selection_before_generating(world, monkeypatch, invalid_target):
    selected = ["box", "second-box"]
    expected = {"box": "8234567890", "second-box": "8345678901"}
    with world["factory"].begin() as session:
        box = session.get(CargoTable, "second-box")
        if invalid_target == "outbound":
            box.status = 1
        elif invalid_target == "date":
            box.date = "2026-10-06 12:00:00"
        elif invalid_target == "archived":
            box.archive = True
        elif invalid_target == "other-packing":
            box.packing_list_uid = None
        elif invalid_target == "stale":
            expected["second-box"] = "stale"
        elif invalid_target == "missing":
            selected[1] = "missing"
            expected = {"box": "8234567890", "missing": None}
        elif invalid_target == "archived-order":
            session.get(OrderTable, "order").archive = True
        elif invalid_target == "archived-packing":
            session.get(PackingListTable, "packing").archive = True
    before = rows(world)
    random = Mock()
    monkeypatch.setattr(number_generation_service.secrets, "randbelow", random)
    response = world["client"].post(PACKING_ROUTE, headers=headers(), json={
        "box_uids": selected, "expected_values": expected,
    })
    assert response.status_code in (404, 409), response.json
    assert rows(world) == before
    assert versions(world) == []
    random.assert_not_called()


@pytest.mark.parametrize("body", [
    {}, [], {"box_uids": []}, {"box_uids": "box"}, {"box_uids": ["box", "box"]},
    {"box_uids": [None]}, {"box_uids": ["box"], "transfer_id": "MANUAL"},
    {"box_uids": ["box"], "expected_values": {}},
    {"box_uids": ["box"], "expected_values": None},
    {"box_uids": ["box"], "expected_values": {"box": 12}},
])
def test_packing_batch_validates_request_shape_without_writes(world, body):
    before = rows(world)
    response = world["client"].post(PACKING_ROUTE, headers=headers(), json=body)
    assert response.status_code == 400, response.json
    assert rows(world) == before
    assert versions(world) == []


@pytest.mark.parametrize("role,status", [(None, 401), ("finance", 403), ("worker", 403), ("customer", 403)])
def test_packing_batch_requires_generation_role(world, role, status):
    response = world["client"].post(
        PACKING_ROUTE, headers=headers(role) if role else {}, json={"box_uids": ["box"]},
    )
    assert response.status_code == status, response.json
    assert versions(world) == []


def test_packing_batch_rolls_back_all_numbers_and_history_on_late_collision_exhaustion(world, monkeypatch):
    with world["factory"].begin() as session:
        session.add(CargoTable(uid="reserved", transfer_id="D800000007L", archive=True))
    monkeypatch.setattr(number_generation_service.secrets, "randbelow", Mock(side_effect=[42] + [7] * 100))
    before = rows(world)
    response = world["client"].post(PACKING_ROUTE, headers=headers(), json={"box_uids": ["box", "second-box"]})
    assert response.status_code == 503, response.json
    assert rows(world) == before
    assert versions(world) == []


def test_concurrent_original_generators_preserve_unique_formatted_numbers(world, monkeypatch):
    values = iter([77, 77, 78])
    start = threading.Barrier(2)
    monkeypatch.setattr(number_generation_service.secrets, "randbelow", lambda upper: next(values))

    def generate(target):
        start.wait(timeout=5)
        if target == "packing":
            return number_generation_service.generate_packing_original_numbers("packing", ["box"], ACTOR)["boxes"][0]
        return number_generation_service.generate_original_number("other-order", "other-cargo", ACTOR)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(generate, target) for target in ("packing", "order")]
        results = [future.result(timeout=15) for future in futures]
    assert {result["transfer_id"] for result in results} == {"D800000077L", "D800000078L"}


def mysql_session_stubs(monkeypatch, *, acquired=1, released=1, release_error=False):
    """Model a pooled MySQL connection without connecting to a real server."""
    events = []

    class Connection:
        dialect = SimpleNamespace(name="mysql")

        def __enter__(self):
            events.append("connection.open")
            return self

        def __exit__(self, *args):
            events.append("connection.close")

        def execute(self, statement, params):
            assert params == {"name": number_generation_service.GENERATION_LOCK_NAME}
            sql = str(statement)
            if "GET_LOCK" in sql:
                events.append("get_lock")
                return SimpleNamespace(scalar=lambda: acquired)
            assert "RELEASE_LOCK" in sql
            events.append("release_lock")
            if release_error:
                raise RuntimeError("release failed")
            return SimpleNamespace(scalar=lambda: released)

        def commit(self):
            events.append("connection.commit")

        def rollback(self):
            events.append("connection.rollback")

        def invalidate(self):
            events.append("connection.invalidate")

    connection = Connection()
    engine = SimpleNamespace(connect=lambda: connection)

    class Session:
        def __init__(self, *, business):
            self.business = business

        def __enter__(self):
            events.append("business.open" if self.business else "probe.open")
            return self

        def __exit__(self, *args):
            events.append("business.close" if self.business else "probe.close")

        def get_bind(self):
            assert not self.business
            return engine

        def commit(self):
            events.append("business.commit")

        def rollback(self):
            events.append("business.rollback")

    def factory(**kwargs):
        if kwargs:
            # Advisory locks are connection-scoped; all writes must use it.
            assert kwargs == {"bind": connection}
        return Session(business=bool(kwargs))

    monkeypatch.setattr(number_generation_service, "SessionFactory", factory)
    return events


def test_mysql_keeps_named_lock_until_pinned_business_session_commits(monkeypatch):
    events = mysql_session_stubs(monkeypatch)
    with number_generation_service._generation_session():
        events.append("business.write")
    assert events == [
        "probe.open", "probe.close", "connection.open", "get_lock", "connection.commit",
        "business.open", "business.write", "business.commit", "business.close",
        "connection.rollback", "release_lock", "connection.commit", "connection.close",
    ]


def test_mysql_business_failure_rolls_back_before_releasing_named_lock(monkeypatch):
    events = mysql_session_stubs(monkeypatch)
    with pytest.raises(RuntimeError, match="write failed"):
        with number_generation_service._generation_session():
            events.append("business.write")
            raise RuntimeError("write failed")
    assert "business.commit" not in events
    assert events.index("business.rollback") < events.index("release_lock")
    assert events[-1] == "connection.close"
    assert "connection.invalidate" not in events


@pytest.mark.parametrize("acquired", [0, None])
def test_mysql_lock_timeout_never_opens_a_write_session(monkeypatch, acquired):
    events = mysql_session_stubs(monkeypatch, acquired=acquired)
    with pytest.raises(number_generation_service.NumberGenerationError) as error:
        with number_generation_service._generation_session():
            pytest.fail("A failed advisory lock must not permit writes")
    assert error.value.code == 503
    assert events == ["probe.open", "probe.close", "connection.open", "get_lock", "connection.close"]


@pytest.mark.parametrize("release_error", [False, True])
def test_mysql_failed_release_invalidates_connection_and_preserves_write_failure(monkeypatch, release_error):
    events = mysql_session_stubs(monkeypatch, released=0, release_error=release_error)
    with pytest.raises(RuntimeError, match="write failed"):
        with number_generation_service._generation_session():
            raise RuntimeError("write failed")
    assert events.index("business.rollback") < events.index("release_lock")
    assert events.index("release_lock") < events.index("connection.invalidate")
    assert events[-1] == "connection.close"


def test_multi_piece_new_master_is_stable_and_retry_does_not_renumber(world, monkeypatch):
    with world['factory'].begin() as session:
        for uid in ['box', 'second-box']:
            session.get(CargoTable, uid).transfer_id = None
    monkeypatch.setattr(number_generation_service.secrets, 'randbelow', Mock(return_value=42))
    request = {'box_uids': ['second-box', 'box'], 'multi_piece': True,
               'expected_values': {'box': None, 'second-box': None}}
    response = world['client'].post(PACKING_ROUTE, headers=headers(), json=request)
    assert response.status_code == 200, response.json
    result = response.json['data']
    assert result['generated_count'] == 2
    assert [(box['uid'], box['transfer_id']) for box in result['boxes']] == [
        ('second-box', 'D800000042L-2'), ('box', 'D800000042L-1')]
    before, history = rows(world), versions(world)
    assert world['client'].post(PACKING_ROUTE, headers=headers(), json=request).status_code == 409
    request['expected_values'] = {box['uid']: box['transfer_id'] for box in result['boxes']}
    again = world['client'].post(PACKING_ROUTE, headers=headers(), json=request)
    assert again.status_code == 200
    assert again.json['data']['generated_count'] == 0
    assert rows(world) == before
    assert versions(world) == history


def test_multi_piece_append_uses_global_max_including_unselected_archived_and_order_numbers(world):
    master = 'D800000042L'
    with world['factory'].begin() as session:
        session.get(CargoTable, 'box').transfer_id = master + '-1'
        session.get(CargoTable, 'second-box').transfer_id = None
        session.add(CargoTable(uid='unselected-child', packing_list_uid='packing', box_number=4,
            transfer_id=master + '-4', status=0, archive=True))
        session.add(OrderTable(uid='suffix-order', order_id=master + '-6', archive=True))
    before = rows(world)
    response = world['client'].post(PACKING_ROUTE, headers=headers(), json={
        'box_uids': ['box', 'second-box'], 'multi_piece': True,
        'expected_values': {'box': master + '-1', 'second-box': None}})
    assert response.status_code == 200, response.json
    assert response.json['data']['generated_count'] == 1
    assert [box['transfer_id'] for box in response.json['data']['boxes']] == [master + '-1', master + '-7']
    assert_only_number_changed(before, rows(world), 'cargos', 'second-box', 'transfer_id', master + '-7')


@pytest.mark.parametrize('invalid', ['ordinary', 'mixed', 'outbound', 'stale', 'other-packing'])
def test_multi_piece_rejects_invalid_selection_atomically(world, monkeypatch, invalid):
    with world['factory'].begin() as session:
        box, second = session.get(CargoTable, 'box'), session.get(CargoTable, 'second-box')
        box.transfer_id, second.transfer_id = 'D800000042L-1', None
        if invalid == 'ordinary':
            box.transfer_id = 'OLD-1'
        elif invalid == 'mixed':
            second.transfer_id = 'D800000043L-1'
        elif invalid == 'outbound':
            second.status = 1
        elif invalid == 'other-packing':
            second.packing_list_uid = None
    before, history = rows(world), versions(world)
    expected = {uid: before['cargos'][uid]['transfer_id'] for uid in ['box', 'second-box']}
    if invalid == 'stale':
        expected['second-box'] = 'old'
    random = Mock()
    monkeypatch.setattr(number_generation_service.secrets, 'randbelow', random)
    response = world['client'].post(PACKING_ROUTE, headers=headers(), json={
        'box_uids': ['box', 'second-box'], 'expected_values': expected, 'multi_piece': True})
    assert response.status_code == 409, response.json
    assert rows(world) == before
    assert versions(world) == history
    random.assert_not_called()


@pytest.mark.parametrize('bad_flag', ['true', 1, None, [], {}])
def test_multi_piece_flag_is_strictly_boolean(world, bad_flag):
    response = world['client'].post(PACKING_ROUTE, headers=headers(), json={
        'box_uids': ['box'], 'multi_piece': bad_flag})
    assert response.status_code == 400


def test_generated_master_does_not_reuse_existing_child_prefix(world, monkeypatch):
    with world['factory'].begin() as session:
        session.add(CargoTable(uid='existing-child', transfer_id='D800000042L-1', archive=True))
    monkeypatch.setattr(number_generation_service.secrets, 'randbelow', Mock(side_effect=[42, 43]))
    response = world['client'].post(ORDER_ROUTE, headers=headers(), json={})
    assert response.status_code == 200, response.json
    assert response.json['data']['order_id'] == 'D800000043L'


def test_concurrent_multi_piece_appends_allocate_different_suffixes(world):
    with world['factory'].begin() as session:
        session.get(CargoTable, 'box').transfer_id = 'D800000042L-1'
        session.add_all([CargoTable(uid=uid, packing_list_uid='packing', box_number=index,
            transfer_id=None, status=0, archive=False) for index, uid in enumerate(['append-a', 'append-b'], start=4)])
    start = threading.Barrier(2)

    def append(uid):
        start.wait(timeout=5)
        return number_generation_service.generate_packing_original_numbers('packing', ['box', uid], ACTOR,
            multi_piece=True, expected_values={'box': 'D800000042L-1', uid: None})

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = [future.result(timeout=15) for future in [executor.submit(append, uid) for uid in ['append-a', 'append-b']]]
    assert {result['boxes'][1]['transfer_id'] for result in results} == {'D800000042L-2', 'D800000042L-3'}
