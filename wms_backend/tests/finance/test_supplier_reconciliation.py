"""Supplier uploads reconcile real ORM facts without mutating warehouse data."""
from decimal import Decimal
from io import BytesIO
import importlib.util
from pathlib import Path

import pytest
from openpyxl import Workbook, load_workbook
from sqlalchemy import create_engine, inspect
from alembic.migration import MigrationContext
from alembic.operations import Operations

from Auth import create_jwt
from data.DB import CargoTable, OrderTable
from data.finance.ledger import FinanceDocument, FinanceDocumentLine
from data.finance.accounting import FinanceJournalEntry
from data.supplier_reconciliation import SupplierReconciliationBatch, SupplierReconciliationRow
from services import supplier_reconciliation_service as reconciliation
from services import finance_ledger_service as ledger
from tests.conftest import TestSessionFactory
from tests.finance.test_ledger import finance, ACTOR, SALES

CLERK = {"id": 703, "user_id": 703, "name": "对账文员", "roles": ["clerk"]}
ADMIN = {"id": 704, "user_id": 704, "name": "管理员", "roles": ["admin"]}


def workbook(rows, headers=None, sheet="对账明细"):
    result = Workbook()
    result.active.title = sheet
    result.active.append(headers or list(reconciliation.HEADERS))
    for row in rows:
        result.active.append(row)
    output = BytesIO()
    result.save(output)
    return output.getvalue()


@pytest.fixture
def supplier(finance, monkeypatch):
    monkeypatch.setattr(ledger, "_today", lambda: "2026-10-06")
    with TestSessionFactory() as session:
        session.add(OrderTable(uid="supplier-order", order_id="ORDER-SUPPLIER", archive=False))
        session.add(CargoTable(uid="supplier-cargo", transfer_id="000123", waybill_id="WB-001",
            target_order_uid="supplier-order", weight=10.125, archive=False, status=1))
        session.add(CargoTable(uid="other-cargo", transfer_id="OTHER", waybill_id="WB-002",
            target_order_uid="supplier-order", weight=5, archive=False, status=1))
        session.commit()
    return finance


def upload(supplier, rows, **extra):
    return reconciliation.upload_batch(workbook(rows), "对账.xlsx", supplier["vendor"]["id"], "2026-10", CLERK, **extra)


def test_upload_creates_only_passed_draft_and_keeps_original_data(supplier):
    result = upload(supplier, [["000123", "WB-001", "10.125", "12.34", "运费"],
        ["OTHER", "WRONG", "6", "50", "异常费用"], ["missing", None, "1", "-3", "扣款"]])
    assert result["batch"]["summary"] == {"total_rows": 3, "passed_rows": 1, "exception_rows": 2,
        "passed_amount": "12.34", "total_valid_amount": "62.34"}
    document = result["batch"]["documents"][0]
    assert document["status"] == "draft" and document["total_amount"] == "12.34"
    assert result["rows"]["items"][0]["original_number"] == "000123"
    with TestSessionFactory() as session:
        assert session.get(CargoTable, "supplier-cargo").weight == 10.125
        assert session.get(CargoTable, "other-cargo").waybill_id == "WB-002"
        assert session.query(FinanceDocument).count() == 1
        assert session.query(FinanceJournalEntry).count() == 0
        source = session.query(SupplierReconciliationRow).filter_by(status="passed").one()
        assert source.finance_document_line_id is not None
        assert session.get(SupplierReconciliationBatch, result["batch"]["id"]).file_bytes
    assert reconciliation.order_costs("supplier-order", CLERK)["confirmed_amount"] == "0.00"
    assert reconciliation.order_costs("supplier-order", CLERK)["pending_amount"] == "12.34"


def test_weight_shortfall_and_optional_waybill(supplier):
    result = upload(supplier, [["000123", None, "10.124", "10", None], ["OTHER", None, "5.002", "20", None]])
    assert result["rows"]["items"][0]["status"] == "passed"
    assert result["rows"]["items"][1]["issues"][0]["code"] == "weight_mismatch"
    assert result["rows"]["items"][0]["system_waybill"] == "WB-001"


@pytest.mark.parametrize("system_weight,uploaded_weight,expected_status", [
    ("10.125", "10.125", "passed"),
    ("10.125", "10.124", "passed"),
    ("10.125", "9.626", "passed"),
    ("10.125", "9.625", "passed"),
    ("10.125", "9.624", "exception"),
    ("10.125", "10.126", "exception"),
    ("10.125", "10.625", "exception"),
    ("9.9999", "10.000", "exception"),
    ("10.0001", "9.500", "exception"),
    ("10.0001", "9.501", "passed"),
])
def test_asymmetric_weight_range_controls_drafts_and_posting(supplier, system_weight, uploaded_weight, expected_status):
    with TestSessionFactory() as session:
        session.get(CargoTable, "supplier-cargo").weight = float(system_weight)
        session.commit()
    result = upload(supplier, [["000123", "WB-001", uploaded_weight, "10", None]])
    row = result["rows"]["items"][0]
    assert row["status"] == expected_status
    assert result["batch"]["weight_difference_range"] == {"min": "-0.500", "max": "0.000"}
    if expected_status == "passed":
        document = result["batch"]["documents"][0]
        posted = ledger.post_document(document["id"], {"version": document["version"]}, ACTOR)
        assert posted["status"] == "posted"
        assert reconciliation.order_costs("supplier-order", CLERK)["confirmed_amount"] == "10.00"
    else:
        assert result["batch"]["documents"] == []
        issue = next(issue for issue in row["issues"] if issue["code"] == "weight_mismatch")
        assert ("大于系统实重" if Decimal(uploaded_weight) > Decimal(system_weight) else "超过 0.5 kg") in issue["message"]
        assert reconciliation.order_costs("supplier-order", CLERK)["confirmed_amount"] == "0.00"


def test_old_positive_difference_draft_cannot_post_under_new_rule(supplier, monkeypatch):
    # An already-created draft from the former symmetric rule must also be checked.
    with monkeypatch.context() as former_rule:
        former_rule.setattr(reconciliation, "_weight_issue", lambda difference: None)
        result = upload(supplier, [["000123", "WB-001", "10.126", "10", None]])
    document = result["batch"]["documents"][0]
    with pytest.raises(ledger.FinanceConflictError, match="未通过对账校验"):
        ledger.post_document(document["id"], {"version": document["version"]}, ACTOR)
    assert ledger.get_document(document["id"], ACTOR)["status"] == "draft"
    with TestSessionFactory() as session:
        assert session.query(FinanceJournalEntry).count() == 0


def test_previously_exceptional_shortfall_can_be_reconciled_with_new_rule(supplier, monkeypatch):
    with monkeypatch.context() as former_rule:
        former_rule.setattr(reconciliation, "_weight_issue", lambda difference: reconciliation._issue("weight_mismatch", "旧重量规则异常"))
        result = upload(supplier, [["000123", "WB-001", "9.625", "10", None]])
    assert result["batch"]["documents"] == []
    revised = reconciliation.reconcile_batch(result["batch"]["id"], {"version": result["batch"]["version"]}, CLERK)
    assert revised["rows"]["items"][0]["status"] == "passed"
    assert revised["batch"]["documents"][0]["total_amount"] == "10.00"


def test_weight_comparison_uses_raw_system_value_before_display_rounding(supplier):
    with TestSessionFactory() as session:
        session.get(CargoTable, "supplier-cargo").weight = 9.9995
        session.commit()
    result = upload(supplier, [["000123", None, "10.001", "10", None]])
    assert result["rows"]["items"][0]["system_weight"] == "10.000"
    assert result["rows"]["items"][0]["issues"][0]["code"] == "weight_mismatch"


def test_file_and_cross_batch_duplicates_never_create_extra_bill(supplier):
    content = workbook([["000123", "WB-001", "10.125", "10", None]])
    first = reconciliation.upload_batch(content, "一.xlsx", supplier["vendor"]["id"], "2026-10", CLERK)
    with pytest.raises(ledger.FinanceConflictError, match="已上传"):
        reconciliation.upload_batch(content, "改文件名.xlsx", supplier["vendor"]["id"], "2026-10", ADMIN)
    second = upload(supplier, [["000123", "WB-001", "10.125", "99", "改金额不能绕过重复"]])
    assert second["rows"]["items"][0]["issues"][0]["code"] == "previous_import_duplicate"
    assert second["batch"]["documents"] == []
    assert len(reconciliation.list_batches(ADMIN)["items"]) == 2
    ledger.cancel_document(first["batch"]["documents"][0]["id"], {"version": 1, "reason": "原草稿取消重核"}, ACTOR)
    retry = reconciliation.reconcile_batch(second["batch"]["id"], {"version": 1}, CLERK)
    assert retry["batch"]["summary"]["passed_rows"] == 1
    assert retry["batch"]["documents"][0]["total_amount"] == "99.00"


def test_duplicates_within_file_and_ambiguous_system_numbers_are_exceptions(supplier):
    with TestSessionFactory() as session:
        session.add(CargoTable(uid="duplicate-other", transfer_id="OTHER", waybill_id="WB-X", weight=5,
            target_order_uid="supplier-order", archive=False))
        session.commit()
    result = upload(supplier, [["000123", None, 10.125, 10, None], ["000123", None, 10.125, 20, None], ["OTHER", None, 5, 30, None]])
    assert result["batch"]["documents"] == []
    assert [row["issues"][0]["code"] for row in result["rows"]["items"]] == ["duplicate_in_file", "duplicate_in_file", "ambiguous_original"]


def test_reconcile_resolves_new_order_and_does_not_duplicate_previous_passed_rows(supplier):
    result = upload(supplier, [["000123", None, 10.125, 10, None], ["LATER", None, 2, 20, None]])
    original_bill_id = result["batch"]["documents"][0]["id"]
    with TestSessionFactory() as session:
        session.add(CargoTable(uid="late-cargo", transfer_id="LATER", waybill_id="", weight=2,
            target_order_uid="supplier-order", archive=False))
        session.commit()
    revised = reconciliation.reconcile_batch(result["batch"]["id"], {"version": 1}, CLERK)
    assert revised["batch"]["summary"]["passed_amount"] == "30.00"
    assert [document["id"] for document in revised["batch"]["documents"]][0] == original_bill_id
    assert len(revised["batch"]["documents"]) == 2
    again = reconciliation.reconcile_batch(result["batch"]["id"], {"version": 2}, ADMIN)
    assert len(again["batch"]["documents"]) == 2
    with pytest.raises(ledger.FinanceConflictError, match="其他操作"):
        reconciliation.reconcile_batch(result["batch"]["id"], {"version": 1}, CLERK)


def test_large_upload_splits_all_successful_rows_into_traceable_drafts(supplier):
    rows = []
    with TestSessionFactory() as session:
        for index in range(201):
            number = f"BULK-{index:03d}"
            session.add(CargoTable(uid=f"bulk-{index}", transfer_id=number, weight=1,
                target_order_uid="supplier-order", archive=False))
            rows.append([number, None, 1, "0.01", None])
        session.commit()
    result = upload(supplier, rows)
    assert result["batch"]["summary"]["passed_rows"] == 201
    assert [document["total_amount"] for document in result["batch"]["documents"]] == ["2.00", "0.01"]
    with TestSessionFactory() as session:
        sources = session.query(SupplierReconciliationRow).filter_by(batch_id=result["batch"]["id"]).all()
        assert len({row.finance_document_line_id for row in sources}) == 201


def test_row_errors_formula_and_unsafe_numeric_precision_remain_visible(supplier):
    result = upload(supplier, [[12345678901234567, None, 1, 10, None], ["000123", None, "=1+9", "1.234", None],
        ["OTHER", None, 0, "bad", None]])
    codes = [{issue["code"] for issue in row["issues"]} for row in result["rows"]["items"]]
    assert "unsafe_excel_number" in codes[0]
    assert codes[1] == {"invalid_weight", "invalid_precision"}
    assert codes[2] == {"nonpositive_weight", "invalid_fee"}
    assert result["rows"]["items"][2]["raw_values"]["最终费用(元)"] == "bad"
    assert result["batch"]["documents"] == []
    assert result["rows"]["total"] == 3


def test_schema_errors_fail_without_creating_batch_and_optional_columns_work(supplier):
    with pytest.raises(ValueError, match="工作表"):
        reconciliation.upload_batch(workbook([["x", 1, 10]], sheet="错误"), "对账.xlsx", supplier["vendor"]["id"], "2026-10", CLERK)
    with pytest.raises(ValueError, match="标题"):
        reconciliation.upload_batch(workbook([["x", 1]], headers=["原单号", "重量(kg)"]), "对账.xlsx", supplier["vendor"]["id"], "2026-10", CLERK)
    with TestSessionFactory() as session:
        assert session.query(SupplierReconciliationBatch).count() == 0
    result = reconciliation.upload_batch(workbook([["000123", 10.125, 10]], headers=["原单号", "重量(kg)", "最终费用(元)"]),
        "对账.xlsx", supplier["vendor"]["id"], "2026-10", CLERK)
    assert result["batch"]["summary"]["passed_rows"] == 1


def test_failed_draft_creation_rolls_back_all_evidence(supplier, monkeypatch):
    def fail(*args, **kwargs):
        raise ValueError("模拟应付草稿保存失败")
    monkeypatch.setattr(reconciliation, "_create_drafts", fail)
    with pytest.raises(ValueError, match="保存失败"):
        upload(supplier, [["000123", None, 10.125, 10, None]])
    with TestSessionFactory() as session:
        assert session.query(SupplierReconciliationBatch).count() == 0
        assert session.query(SupplierReconciliationRow).count() == 0


def test_posting_rechecks_source_and_cost_becomes_actual_only_once(supplier):
    result = upload(supplier, [["000123", "WB-001", 10.125, 10, None]])
    doc = result["batch"]["documents"][0]
    with TestSessionFactory() as session:
        session.get(CargoTable, "supplier-cargo").weight = 20
        session.commit()
    with pytest.raises(ledger.FinanceConflictError, match="已变化"):
        ledger.post_document(doc["id"], {"version": 1}, ACTOR)
    assert ledger.get_document(doc["id"], ACTOR)["status"] == "draft"
    with TestSessionFactory() as session:
        session.get(CargoTable, "supplier-cargo").weight = 10.125
        session.commit()
    posted = ledger.post_document(doc["id"], {"version": 1}, ACTOR)
    assert reconciliation.order_costs("supplier-order", CLERK)["confirmed_amount"] == "10.00"
    assert reconciliation.order_costs("supplier-order", CLERK)["pending_amount"] == "0.00"
    reversal = ledger.reverse_document(doc["id"], {"version": posted["version"], "document_date": "2026-10-06", "reason": "供应商费用撤回"}, ACTOR)
    assert reversal["credit"]["document_type"] == "vendor_credit"
    assert reconciliation.order_costs("supplier-order", CLERK)["confirmed_amount"] == "0.00"


def test_import_metadata_edit_preserves_line_source_and_changed_amount_rejected(supplier):
    result = upload(supplier, [["000123", "WB-001", 10.125, 10, "运费"]])
    doc = ledger.get_document(result["batch"]["documents"][0]["id"], ACTOR)
    line = doc["lines"][0]
    body = {"version": doc["version"], "memo": "财务核对附件", "lines": [{"description": line["description"],
        "quantity": line["quantity"], "unit_price": line["unit_price"], "tax_rate": line["tax_rate"], "order_uid": line["order_uid"]}]}
    edited = ledger.update_document(doc["id"], body, ACTOR)
    assert edited["lines"][0]["id"] == line["id"]
    body["version"] = edited["version"]
    body["lines"][0]["unit_price"] = "99"
    with pytest.raises(ledger.FinanceConflictError, match="导入"):
        ledger.update_document(doc["id"], body, ACTOR)


def test_http_roles_upload_vendor_options_details_and_finance_post_boundary(supplier, client):
    headers = {"x-token": create_jwt(CLERK)}
    options = client.get("/api/supplier-reconciliation/vendors", headers=headers)
    assert options.status_code == 200
    assert set(options.get_json()["data"]["items"][0]) == {"id", "name"}
    uploaded = client.post("/api/supplier-reconciliation/batches", data={"file": (BytesIO(workbook([["000123", None, 10.125, 10, None]])), "对账.xlsx"),
        "vendor_id": supplier["vendor"]["id"], "period": "2026-10"}, headers=headers)
    assert uploaded.status_code == 200
    data = uploaded.get_json()["data"]
    admin_headers = {"x-token": create_jwt(ADMIN)}
    assert client.get(f"/api/supplier-reconciliation/batches/{data['batch']['id']}", headers=admin_headers).status_code == 200
    assert client.post(f"/api/finance/v2/documents/{data['batch']['documents'][0]['id']}/post", json={"version": 1}, headers=headers).status_code == 403
    assert client.get("/api/supplier-reconciliation/batches", headers={"x-token": create_jwt(SALES)}).status_code == 403
    assert client.get("/api/supplier-reconciliation/template", headers=headers).status_code == 200


def test_reconciliation_migration_round_trip_without_business_db():
    path = Path(__file__).resolve().parents[2] / "alembic" / "versions" / "20261006_79e4f5a6b7c8_supplier_reconciliation.py"
    spec = importlib.util.spec_from_file_location("supplier_migration_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        context = MigrationContext.configure(connection)
        module.op = Operations(context)
        module.upgrade()
        tables = inspect(connection).get_table_names()
        assert "supplier_reconciliation_batches" in tables and "supplier_reconciliation_rows" in tables
        assert {column["name"] for column in inspect(connection).get_columns("supplier_reconciliation_rows")} >= {"raw_json", "finance_document_line_id"}
        module.downgrade()
        assert inspect(connection).get_table_names() == []


def test_order_number_fallback_uses_active_real_total_and_attributes_whole_fee(supplier):
    with TestSessionFactory() as session:
        session.get(OrderTable, "supplier-order").total_weight = 999
        session.add(CargoTable(uid="archived-cargo", transfer_id="ARCHIVED", weight=200,
            target_order_uid="supplier-order", archive=True))
        session.commit()
    result = upload(supplier, [["ORDER-SUPPLIER", "供应商整单参考号", "14.125", "80", "整单运费"]])
    row = result["rows"]["items"][0]
    assert row["status"] == "passed" and row["match_type"] == "order"
    assert row["cargo_uid"] is None and row["order_uid"] == "supplier-order"
    assert row["system_weight_scope"] == "order_total"
    assert row["system_weight"] == "15.125" and row["weight_difference"] == "-1.000"
    assert row["system_waybill"] is None and row["waybill_number"] == "供应商整单参考号"
    assert result["batch"]["order_weight_difference_range"] == {
        "min": "-5.000", "max": "0.000", "min_inclusive": True, "max_inclusive": False,
    }
    doc = result["batch"]["documents"][0]
    assert ledger.get_document(doc["id"], ACTOR)["lines"][0]["order_uid"] == "supplier-order"
    costs = reconciliation.order_costs("supplier-order", CLERK)
    assert costs["pending_amount"] == "80.00" and costs["confirmed_amount"] == "0.00"
    assert costs["items"][0]["match_type"] == "order"
    assert costs["items"][0]["source_system_weight"] == "15.125"
    assert costs["items"][0]["source_original_number"] == "ORDER-SUPPLIER"
    with pytest.raises(PermissionError):
        ledger.post_document(doc["id"], {"version": 1}, CLERK)
    posted = ledger.post_document(doc["id"], {"version": 1}, ACTOR)
    assert posted["status"] == "posted"
    assert reconciliation.order_costs("supplier-order", CLERK)["confirmed_amount"] == "80.00"
    with TestSessionFactory() as session:
        assert session.query(FinanceJournalEntry).filter_by(source_id=str(doc["id"])).count() == 1
        assert session.query(CargoTable).count() == 3
    reversal = ledger.reverse_document(doc["id"], {"version": posted["version"],
        "document_date": "2026-10-06", "reason": "整单费用撤回"}, ACTOR)
    assert reversal["credit"]["lines"][0]["order_uid"] == "supplier-order"
    assert reconciliation.order_costs("supplier-order", CLERK)["confirmed_amount"] == "0.00"


@pytest.mark.parametrize("cargo_weight,uploaded_weight,expected", [
    ("10.125", "10.125", "passed"),  # Exact -5 kg boundary against total 15.125.
    ("10.125", "15.124", "passed"),
    ("10.125", "15.125", "exception"),  # Equality is explicitly excluded for orders.
    ("10.125", "15.126", "exception"),
    ("10.125", "10.124", "exception"),
    ("10.1251", "10.125", "exception"),  # No rounding may hide a >5 kg shortfall.
    ("10.1249", "15.125", "exception"),
])
def test_order_weight_range_is_minus_five_inclusive_to_zero_exclusive(supplier, cargo_weight, uploaded_weight, expected):
    with TestSessionFactory() as session:
        session.get(CargoTable, "supplier-cargo").weight = float(cargo_weight)
        session.commit()
    result = upload(supplier, [["ORDER-SUPPLIER", None, uploaded_weight, "10", None]])
    row = result["rows"]["items"][0]
    assert row["status"] == expected
    if expected == "passed":
        doc = result["batch"]["documents"][0]
        assert ledger.post_document(doc["id"], {"version": 1}, ACTOR)["status"] == "posted"
    else:
        assert {issue["code"] for issue in row["issues"]} == {"weight_mismatch"}
        assert result["batch"]["documents"] == []


def test_package_original_number_has_priority_even_when_same_order_number_exists(supplier):
    with TestSessionFactory() as session:
        session.get(CargoTable, "other-cargo").transfer_id = "ORDER-SUPPLIER"
        session.commit()
    result = upload(supplier, [["ORDER-SUPPLIER", None, "4.900", "10", None]])
    row = result["rows"]["items"][0]
    assert row["status"] == "passed" and row["match_type"] == "cargo"
    assert row["cargo_uid"] == "other-cargo" and row["system_weight"] == "5.000"


@pytest.mark.parametrize("source_problem,expected_code", [
    ("archive", "archived_source"), ("duplicate", "ambiguous_original"),
    ("unassigned", "order_not_found"), ("weight", "invalid_system_weight"),
    ("package_tolerance", "weight_mismatch"),
])
def test_invalid_package_candidate_never_falls_back_to_order(supplier, source_problem, expected_code):
    with TestSessionFactory() as session:
        cargo = session.get(CargoTable, "other-cargo")
        cargo.transfer_id = "ORDER-SUPPLIER"
        if source_problem == "archive":
            cargo.archive = True
        elif source_problem == "duplicate":
            session.add(CargoTable(uid="duplicate-id", transfer_id="ORDER-SUPPLIER", weight=5,
                target_order_uid="supplier-order", archive=False))
        elif source_problem == "unassigned":
            cargo.target_order_uid = None
        elif source_problem == "weight":
            cargo.weight = 0
        session.commit()
    result = upload(supplier, [["ORDER-SUPPLIER", None, "1.000", "10", None]])
    assert result["rows"]["items"][0]["issues"][0]["code"] == expected_code
    assert result["batch"]["documents"] == []


def test_order_fallback_rejects_ambiguous_number_and_does_not_match_internal_uid(supplier):
    with TestSessionFactory() as session:
        session.add(OrderTable(uid="duplicate-order", order_id="ORDER-SUPPLIER", archive=True))
        session.commit()
    result = upload(supplier, [["ORDER-SUPPLIER", None, "14", "10", None],
        ["supplier-order", None, "14", "10", None], ["order-supplier", None, "14", "10", None]])
    assert [row["issues"][0]["code"] for row in result["rows"]["items"]] == [
        "ambiguous_order", "original_not_found", "original_not_found",
    ]
    assert result["batch"]["documents"] == []


@pytest.mark.parametrize("source_problem,expected_code", [
    ("archive_order", "archived_source"), ("archive_cargos", "invalid_system_weight"),
    ("negative_weight", "invalid_system_weight"), ("missing_weight", "invalid_system_weight"),
])
def test_invalid_order_total_is_an_exception(supplier, source_problem, expected_code):
    with TestSessionFactory() as session:
        if source_problem == "archive_order":
            session.get(OrderTable, "supplier-order").archive = True
        elif source_problem == "archive_cargos":
            for cargo in session.query(CargoTable).all():
                cargo.archive = True
        else:
            session.get(CargoTable, "supplier-cargo").weight = -1 if source_problem == "negative_weight" else None
        session.commit()
    result = upload(supplier, [["ORDER-SUPPLIER", None, "1", "10", None]])
    assert result["rows"]["items"][0]["issues"][0]["code"] == expected_code
    assert result["batch"]["documents"] == []


@pytest.mark.parametrize("first_kind,second_kind", [("order", "order"), ("cargo", "order"), ("order", "cargo")])
def test_order_fee_duplicate_detection_includes_package_coverage(supplier, first_kind, second_kind):
    values = {"order": ["ORDER-SUPPLIER", None, "14.125", "10", None],
        "cargo": ["000123", None, "10.125", "10", None]}
    first = upload(supplier, [values[first_kind]])
    second_values = [*values[second_kind]]
    second_values[3] = "99"
    second = upload(supplier, [second_values])
    assert second["rows"]["items"][0]["issues"][0]["code"] == "previous_import_duplicate"
    assert second["batch"]["documents"] == []
    ledger.cancel_document(first["batch"]["documents"][0]["id"], {"version": 1, "reason": "取消原对账重新核对"}, ACTOR)
    retry = reconciliation.reconcile_batch(second["batch"]["id"], {"version": 1}, CLERK)
    assert retry["batch"]["summary"]["passed_rows"] == 1


def test_whole_order_and_package_rows_in_same_file_are_both_excluded(supplier):
    result = upload(supplier, [["000123", None, "10.125", "10", None],
        ["ORDER-SUPPLIER", None, "14.125", "99", None]])
    assert result["batch"]["documents"] == []
    assert [row["issues"][0]["code"] for row in result["rows"]["items"]] == ["overlapping_in_file", "overlapping_in_file"]


@pytest.mark.parametrize("shipment_change", ["new_cargo", "new_waybill"])
def test_partially_changed_order_shipment_still_requires_review_for_unchanged_billed_members(supplier, shipment_change):
    first = upload(supplier, [["ORDER-SUPPLIER", None, "14.125", "10", None]])
    with TestSessionFactory() as session:
        if shipment_change == "new_cargo":
            session.add(CargoTable(uid="later-member", transfer_id="LATER", weight=1,
                target_order_uid="supplier-order", archive=False))
        else:
            session.get(CargoTable, "supplier-cargo").waybill_id = "LATER-WAYBILL"
        session.commit()
    second = upload(supplier, [["ORDER-SUPPLIER", None, "14.125", "99", None]])
    assert second["rows"]["items"][0]["issues"][0]["code"] == "previous_import_duplicate"
    assert second["batch"]["documents"] == []


@pytest.mark.parametrize("shipment_change", ["all_new_cargos", "all_new_waybills"])
def test_disjoint_new_order_shipments_are_not_permanently_blocked_by_order_uid(supplier, shipment_change):
    first = upload(supplier, [["ORDER-SUPPLIER", None, "14.125", "10", None]])
    with TestSessionFactory() as session:
        for cargo in session.query(CargoTable).all():
            if shipment_change == "all_new_cargos":
                cargo.archive = True
            else:
                cargo.waybill_id = "LATER-" + cargo.uid
        if shipment_change == "all_new_cargos":
            session.add(CargoTable(uid="new-shipment", transfer_id="LATER", weight=15.125,
                target_order_uid="supplier-order", archive=False))
        session.commit()
    second = upload(supplier, [["ORDER-SUPPLIER", None, "14.125", "99", None]])
    assert second["rows"]["items"][0]["status"] == "passed"
    assert second["batch"]["documents"][0]["id"] != first["batch"]["documents"][0]["id"]


@pytest.mark.parametrize("first_kind,second_kind", [("cargo", "order"), ("order", "cargo"), ("order", "order")])
def test_charged_cargo_moving_order_does_not_evade_shipment_duplicate_check(supplier, first_kind, second_kind):
    first_values = ["000123", None, "10.125", "10", None] if first_kind == "cargo" else ["ORDER-SUPPLIER", None, "14.125", "10", None]
    upload(supplier, [first_values])
    with TestSessionFactory() as session:
        session.add(OrderTable(uid="new-target-order", order_id="NEW-TARGET-ORDER", archive=False))
        session.get(CargoTable, "supplier-cargo").target_order_uid = "new-target-order"
        session.commit()
    second_values = ["000123", None, "10.125", "99", None] if second_kind == "cargo" else ["NEW-TARGET-ORDER", None, "9.125", "99", None]
    second = upload(supplier, [second_values])
    assert second["rows"]["items"][0]["issues"][0]["code"] == "previous_import_duplicate"
    assert second["batch"]["documents"] == []


@pytest.mark.parametrize("source_change", ["weight", "same_total", "new_cargo", "archive", "move", "rename", "ambiguous_order", "new_package_match"])
def test_posting_order_fee_revalidates_total_membership_and_match_priority(supplier, source_change):
    result = upload(supplier, [["ORDER-SUPPLIER", None, "14.125", "10", None]])
    doc = result["batch"]["documents"][0]
    with TestSessionFactory() as session:
        cargo = session.get(CargoTable, "supplier-cargo")
        if source_change == "weight":
            cargo.weight = 11
        elif source_change == "same_total":
            cargo.weight += 1
            session.get(CargoTable, "other-cargo").weight -= 1
        elif source_change == "new_cargo":
            session.add(CargoTable(uid="new-member", transfer_id="NEW", weight=1,
                target_order_uid="supplier-order", archive=False))
        elif source_change == "archive":
            cargo.archive = True
        elif source_change == "move":
            cargo.target_order_uid = None
        elif source_change == "rename":
            session.get(OrderTable, "supplier-order").order_id = "RENAMED"
        elif source_change == "ambiguous_order":
            session.add(OrderTable(uid="duplicate-order", order_id="ORDER-SUPPLIER", archive=False))
        else:
            cargo.transfer_id = "ORDER-SUPPLIER"
        session.commit()
    with pytest.raises(ledger.FinanceConflictError, match="已变化"):
        ledger.post_document(doc["id"], {"version": 1}, ACTOR)
    assert ledger.get_document(doc["id"], ACTOR)["status"] == "draft"
    assert reconciliation.order_costs("supplier-order", CLERK)["confirmed_amount"] == "0.00"
    with TestSessionFactory() as session:
        assert session.query(FinanceJournalEntry).count() == 0


def test_order_equality_draft_cannot_post_even_if_former_rule_allowed_it(supplier, monkeypatch):
    with monkeypatch.context() as former_rule:
        former_rule.setattr(reconciliation, "_order_weight_issue", lambda difference: None)
        result = upload(supplier, [["ORDER-SUPPLIER", None, "15.125", "10", None]])
    doc = result["batch"]["documents"][0]
    with pytest.raises(ledger.FinanceConflictError, match="未通过对账校验"):
        ledger.post_document(doc["id"], {"version": 1}, ACTOR)


def test_order_exception_can_be_reconciled_once_after_missing_order_is_created(supplier):
    result = upload(supplier, [["LATER-ORDER", None, "9", "10", None]])
    with TestSessionFactory() as session:
        session.add(OrderTable(uid="later-order", order_id="LATER-ORDER", archive=False))
        session.add(CargoTable(uid="later-order-cargo", transfer_id="OTHER-NUMBER", weight=10,
            target_order_uid="later-order", archive=False))
        session.commit()
    retry = reconciliation.reconcile_batch(result["batch"]["id"], {"version": 1}, CLERK)
    assert retry["rows"]["items"][0]["match_type"] == "order"
    assert retry["rows"]["items"][0]["status"] == "passed"
    again = reconciliation.reconcile_batch(result["batch"]["id"], {"version": 2}, CLERK)
    assert again["batch"]["documents"] == retry["batch"]["documents"]
