import random
import time
from typing import Any

from sqlalchemy import (
    Boolean,
    Column,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Table,
    Text,
)
from sqlalchemy.orm import relationship

from .database import Base, SessionFactory


# ---------------------------------------------------------------------------
# Association table for Order-Customer many-to-many relationship
# ---------------------------------------------------------------------------

order_customers = Table(
    "order_customers",
    Base.metadata,
    Column("order_uid", String(32), ForeignKey("orders.uid"), primary_key=True),
    Column("customer_id", Integer, ForeignKey("customers.id"), primary_key=True),
)


class RecordExist(Exception):
    def __str__(self):
        return "Record is Existed"


RECEIPT_LOCKED_MESSAGE = "订单已生成收据，包裹重量、包裹归属和报价已锁定"
ORDER_REVISION_OPEN_MESSAGE = "订单正在修订，暂不能出库或分配奖金"


class ReceiptLockedError(ValueError):
    """订单已生成收据，禁止修改计费基础。"""

    def __init__(self):
        super().__init__(RECEIPT_LOCKED_MESSAGE)


class OrderRevisionOpenError(ValueError):
    """订单处于收据修订窗口，禁止产生新的下游快照。"""

    def __init__(self):
        super().__init__(ORDER_REVISION_OPEN_MESSAGE)


# ---------------------------------------------------------------------------
# SQLAlchemy ORM table definitions
# ---------------------------------------------------------------------------


class OrderTable(Base):
    __tablename__ = "orders"

    uid = Column(String(32), primary_key=True)
    order_id = Column(String(128))
    customer_name = Column(String(256))
    transportation = Column(String(128))
    receiver = Column(String(256))
    receiver_phone = Column(String(64))
    mail = Column(String(256))
    country = Column(String(128))
    province = Column(String(128))
    city = Column(String(128))
    address = Column(Text)
    en_name = Column(String(256))
    cn_name = Column(String(256))
    total_weight = Column(Float)
    cargo_count = Column(Integer, default=0)
    archive = Column(Boolean, default=False)
    post_code = Column(String(64))
    zip_code = Column(String(64))
    order_date = Column(String(32))
    tag_all = Column(String(256))
    create_date = Column(String(32))
    update_date = Column(String(32))

    # Foreign key to user (salesman/businessman) - Many orders to one user
    salesman_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    # One order → many cargos (used to derive cargo_uid_list dynamically)
    cargos = relationship(
        "CargoTable",
        back_populates="order",
        foreign_keys="CargoTable.target_order_uid",
        lazy="select",
    )

    # Many-to-one relationship: many orders can have the same salesman
    salesman = relationship(
        "UserTable",
        foreign_keys=[salesman_id],
        lazy="select",
    )

    # Many-to-many relationship with customers
    customers = relationship(
        "CustomerTable",
        secondary="order_customers",
        back_populates="orders",
        lazy="select",
    )


class CargoTable(Base):
    __tablename__ = "cargos"

    uid = Column(String(32), primary_key=True)
    origin_id = Column(String(128))
    transfer_id = Column(String(256), default="")
    tag = Column(String(128), default="init")
    count = Column(Integer, default=0)
    weight = Column(Float, default=0.0)
    real_en_name = Column(String(256))
    price = Column(Float)
    status = Column(Integer, default=0)
    archive = Column(Boolean, default=False)
    date = Column(String(32))
    waybill_id = Column(String(256), default="")
    target_order_uid = Column(String(32), ForeignKey("orders.uid"))
    # Unified box fields (merged from legacy boxes table)
    packing_list_uid = Column(
        String(32), ForeignKey("packing_lists.uid"), nullable=True
    )
    item_name = Column(String(256), nullable=True)
    item_details = Column(Text, nullable=True)
    remark = Column(String(512), nullable=True)
    box_number = Column(Integer, nullable=True)
    piece_count = Column(Integer, nullable=True)
    bonus_item_id = Column(Integer, ForeignKey("bonus_items.id"), nullable=True)
    bonus_assigned = Column(Boolean, default=False)
    bonus_assigned_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    bonus_assigned_date = Column(String(32), nullable=True)
    box_status = Column(String(32), default="pending")
    create_date = Column(String(32))
    update_date = Column(String(32))

    order = relationship("OrderTable", back_populates="cargos")
    packing_list = relationship(
        "PackingListTable", back_populates="boxes", lazy="select"
    )
    workers = relationship("BoxWorkerTable", back_populates="box", lazy="select")


# ---------------------------------------------------------------------------
# Base model class - SQLAlchemy standard implementation
# ---------------------------------------------------------------------------


class MySQLModel:
    """SQLAlchemy-based model class with standard CRUD operations."""

    def __init__(self, table_class):
        self.table_class = table_class
        self._columns = {c.name for c in table_class.__table__.columns}

    @property
    def data_point(self) -> dict:
        """Compatibility shim for legacy code that accesses model.data_point."""
        s = SessionFactory()
        try:
            records = s.query(self.table_class).all()
            return {r.uid: self._to_dict(r) for r in records}
        finally:
            s.close()

    # ------------------------------------------------------------------
    # CRUD operations
    # ------------------------------------------------------------------

    def create(self, record: dict) -> str:
        """Create a new record. Automatically generates uid and create_date."""
        uid = str(int(time.time() * 1000000)) + str(random.randint(10, 99))

        # Filter only valid column names from the input record
        db_dict = {k: v for k, v in record.items() if k in self._columns}
        db_dict["uid"] = uid
        db_dict["create_date"] = time.strftime("%Y-%m-%d %H:%M")

        s = SessionFactory()
        try:
            db_record = self.table_class(**db_dict)
            s.add(db_record)
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

        return uid

    def archive(self, uid: str):
        """Soft delete (archive) a record by setting archive=True."""
        s = SessionFactory()
        try:
            db_record = (
                s.query(self.table_class).filter(self.table_class.uid == uid).first()
            )
            if db_record:
                db_record.archive = True
                s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    def delete(self, uid: str):
        """Hard delete a record from the database."""
        s = SessionFactory()
        try:
            db_record = (
                s.query(self.table_class).filter(self.table_class.uid == uid).first()
            )
            if db_record:
                s.delete(db_record)
                s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    def update(self, uid: str, record: dict):
        """Update an existing record."""
        s = SessionFactory()
        try:
            db_record = (
                s.query(self.table_class).filter(self.table_class.uid == uid).first()
            )
            if db_record is None:
                return
            db_record.update_date = time.strftime("%Y-%m-%d %H:%M")
            for k, v in record.items():
                # Skip virtual fields and None values
                if k not in self._columns:
                    continue
                if v is None:
                    continue
                setattr(db_record, k, v)
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    def read(self, uid=None, _fields=None, except_fields=None):
        """Read records. If uid is provided, return single record; otherwise return all."""
        if _fields is None:
            _fields = []
        if except_fields is None:
            except_fields = []

        s = SessionFactory()
        try:
            q = s.query(self.table_class).filter(
                self.table_class.archive == False  # noqa: E712
            )
            import logging

            if uid is not None:
                db_record = q.filter(self.table_class.uid == uid).first()
                if db_record is None:
                    return None
                return self._to_dict(db_record, _fields, except_fields)
            else:
                records = q.all()
                return [self._to_dict(r, _fields, except_fields) for r in records]
        finally:
            s.close()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _to_dict(
        self, record, _fields: list = None, except_fields: list = None
    ) -> dict:
        """Convert ORM record to dictionary."""
        if _fields is None:
            _fields = []
        if except_fields is None:
            except_fields = []

        result: dict[str, Any] = {}

        for col_name in (c.name for c in record.__table__.columns):
            if except_fields and col_name in except_fields:
                continue
            if _fields and col_name not in _fields:
                continue
            result[col_name] = getattr(record, col_name)

        # For order records: derive cargo_uid_list from the ORM relationship
        if hasattr(record, "cargos"):
            if "cargo_uid_list" not in (except_fields or []):
                if not _fields or "cargo_uid_list" in _fields:
                    result["cargo_uid_list"] = [
                        c.uid for c in record.cargos if not c.archive
                    ]

        # For order records: derive salesman info from the ORM relationship
        if hasattr(record, "salesman"):
            if "salesman" not in (except_fields or []):
                if not _fields or "salesman" in _fields:
                    if record.salesman:
                        result["salesman"] = {
                            "id": record.salesman.id,
                            "name": record.salesman.name,
                            "phone": record.salesman.phone,
                        }
                    else:
                        result["salesman"] = None

        # For order records: derive customer_ids from the ORM relationship
        if hasattr(record, "customers"):
            if "customer_ids" not in (except_fields or []):
                if not _fields or "customer_ids" in _fields:
                    result["customer_ids"] = [c.id for c in record.customers]
        return result


# ---------------------------------------------------------------------------
# Concrete model subclasses
# ---------------------------------------------------------------------------


class OrderModel(MySQLModel):
    def update(self, uid: str, record: dict):
        """更新订单；修订窗口只允许绕过计费基础锁，不能绕过归档保护。"""
        s = SessionFactory()
        try:
            db_record = (
                s.query(OrderTable)
                .filter(OrderTable.uid == uid)
                .with_for_update()
                .first()
            )
            if db_record is None:
                return

            weight_changed = False
            if "total_weight" in record and record.get("total_weight") is not None:
                try:
                    weight_changed = float(record.get("total_weight") or 0) != float(
                        db_record.total_weight or 0
                    )
                except (TypeError, ValueError):
                    weight_changed = record.get("total_weight") != db_record.total_weight
            archive_changed = (
                "archive" in record
                and record.get("archive") is not None
                and bool(record.get("archive")) != bool(db_record.archive)
            )
            if archive_changed:
                ensure_order_without_receipt_history(s, uid, order=db_record)
            if weight_changed:
                ensure_order_receipt_unlocked(s, uid, order=db_record)

            db_record.update_date = time.strftime("%Y-%m-%d %H:%M")
            for k, v in record.items():
                if k not in self._columns or v is None:
                    continue
                setattr(db_record, k, v)
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    def archive(self, uid: str):
        s = SessionFactory()
        try:
            order = (
                s.query(OrderTable)
                .filter(OrderTable.uid == uid)
                .with_for_update()
                .first()
            )
            if order is None:
                return
            ensure_order_without_receipt_history(s, uid, order=order)
            order.archive = True
            order.update_date = time.strftime("%Y-%m-%d %H:%M")
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    def delete(self, uid: str):
        s = SessionFactory()
        try:
            order = (
                s.query(OrderTable)
                .filter(OrderTable.uid == uid)
                .with_for_update()
                .first()
            )
            if order is None:
                return
            ensure_order_without_receipt_history(s, uid, order=order)
            s.delete(order)
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    def set_salesman(self, order_uid: str, user_id: int) -> bool:
        """Set the salesman for an order."""
        s = SessionFactory()
        try:
            order = s.query(OrderTable).filter(OrderTable.uid == order_uid).first()
            if order is None:
                return False
            order.salesman_id = user_id
            order.update_date = time.strftime("%Y-%m-%d %H:%M")
            s.commit()
            return True
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    def remove_salesman(self, order_uid: str) -> bool:
        """Remove the salesman from an order."""
        s = SessionFactory()
        try:
            order = s.query(OrderTable).filter(OrderTable.uid == order_uid).first()
            if order is None:
                return False
            order.salesman_id = None
            order.update_date = time.strftime("%Y-%m-%d %H:%M")
            s.commit()
            return True
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    def is_salesman(self, order_uid: str, user_id: int) -> bool:
        """Check if a user is the salesman for an order."""
        s = SessionFactory()
        try:
            order = s.query(OrderTable).filter(OrderTable.uid == order_uid).first()
            if order is None:
                return False
            return order.salesman_id == user_id
        finally:
            s.close()

    def get_salesman(self, order_uid: str) -> dict | None:
        """Get the salesman for an order."""
        s = SessionFactory()
        try:
            order = s.query(OrderTable).filter(OrderTable.uid == order_uid).first()
            if order is None or order.salesman is None:
                return None
            return {
                "id": order.salesman.id,
                "name": order.salesman.name,
                "phone": order.salesman.phone,
            }
        finally:
            s.close()

    # ------------------------------------------------------------------
    # Customer relationship management (many-to-many)
    # ------------------------------------------------------------------

    def add_customer(self, order_uid: str, customer_id: int) -> bool:
        """Add a customer to an order."""
        from data.customer.Customer import CustomerTable

        s = SessionFactory()
        try:
            order = s.query(OrderTable).filter(OrderTable.uid == order_uid).first()
            if order is None:
                return False
            customer = (
                s.query(CustomerTable).filter(CustomerTable.id == customer_id).first()
            )
            if customer is None:
                return False
            if customer not in order.customers:
                order.customers.append(customer)
                order.update_date = time.strftime("%Y-%m-%d %H:%M")
                s.commit()
            return True
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    def remove_customer(self, order_uid: str, customer_id: int) -> bool:
        """Remove a customer from an order."""
        from data.customer.Customer import CustomerTable

        s = SessionFactory()
        try:
            order = s.query(OrderTable).filter(OrderTable.uid == order_uid).first()
            if order is None:
                return False
            customer = (
                s.query(CustomerTable).filter(CustomerTable.id == customer_id).first()
            )
            if customer is None:
                return False
            if customer in order.customers:
                order.customers.remove(customer)
                order.update_date = time.strftime("%Y-%m-%d %H:%M")
                s.commit()
            return True
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    def set_customers(self, order_uid: str, customer_ids: list) -> bool:
        """Set the customers for an order (replaces existing associations)."""
        from data.customer.Customer import CustomerTable

        s = SessionFactory()
        try:
            order = s.query(OrderTable).filter(OrderTable.uid == order_uid).first()
            if order is None:
                return False
            customers = (
                s.query(CustomerTable).filter(CustomerTable.id.in_(customer_ids)).all()
            )
            order.customers = customers
            order.update_date = time.strftime("%Y-%m-%d %H:%M")
            s.commit()
            return True
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    def get_customers(self, order_uid: str) -> list:
        """Get all customers for an order."""
        s = SessionFactory()
        try:
            order = s.query(OrderTable).filter(OrderTable.uid == order_uid).first()
            if order is None:
                return []
            return [{"id": c.id, "name": c.name} for c in order.customers]
        finally:
            s.close()


class CargoModel(MySQLModel):
    def _lock_box_cost(self, session, box, now: str):
        if not box.target_order_uid:
            return
        if not str(box.waybill_id or "").strip():
            return
        try:
            weight = float(box.weight or 0)
        except (TypeError, ValueError):
            weight = 0
        if weight <= 0:
            raise ValueError("Box weight is required before outbound")

        order = session.query(OrderTable).filter(OrderTable.uid == box.target_order_uid).first()
        if order is None:
            raise ValueError("Target order not found")
        transportation_name = str(order.transportation or "").strip()
        mode = None
        if transportation_name:
            mode = (
                session.query(TransportationModeTable)
                .filter(
                    TransportationModeTable.archive == False,  # noqa: E712
                    TransportationModeTable.name == transportation_name,
                )
                .first()
            )

        session.query(BoxCostRecordTable).filter(
            BoxCostRecordTable.box_uid == box.uid
        ).delete()
        unit_cost = 0 if not mode else float(mode.cost)
        transportation_mode_id = mode.id if mode else None
        locked_transportation_name = mode.name if mode else transportation_name
        session.add(
            BoxCostRecordTable(
                box_uid=box.uid,
                packing_list_uid=box.packing_list_uid,
                order_uid=box.target_order_uid,
                transportation_mode_id=transportation_mode_id,
                transportation_name=locked_transportation_name,
                waybill_id=box.waybill_id,
                weight=weight,
                unit_cost=unit_cost,
                total_cost=unit_cost * weight,
                create_date=now,
            )
        )

    def unbind_from_order(self, uid: str) -> bool:
        """Detach a cargo from its order by clearing target_order_uid."""
        s = SessionFactory()
        try:
            db_record = (
                s.query(self.table_class)
                .filter(self.table_class.uid == uid)
                .with_for_update()
                .first()
            )
            if db_record is None:
                return False

            if db_record.target_order_uid:
                ensure_order_receipt_unlocked(s, db_record.target_order_uid)

            db_record.target_order_uid = None
            db_record.update_date = time.strftime("%Y-%m-%d %H:%M")

            # Non-outbound box should stay in pending-outbound when detached.
            if db_record.packing_list_uid and int(db_record.status or 0) != 1:
                db_record.status = 0

            s.commit()
            return True
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    def update(self, uid: str, record: dict):
        """Update cargo and keep legacy box fields synchronized for unified rows."""
        s = SessionFactory()
        try:
            db_record = (
                s.query(self.table_class)
                .filter(self.table_class.uid == uid)
                .with_for_update()
                .first()
            )
            if db_record is None:
                return

            current_order_uid = db_record.target_order_uid
            next_order_uid = (
                record.get("target_order_uid")
                if "target_order_uid" in record
                else current_order_uid
            )
            next_order_uid = next_order_uid or None
            target_changed = next_order_uid != current_order_uid
            archive_changed = (
                "archive" in record
                and record.get("archive") is not None
                and bool(record.get("archive")) != bool(db_record.archive)
            )
            weight_changed = False
            if "weight" in record and record.get("weight") is not None:
                try:
                    weight_changed = float(record.get("weight")) != float(
                        db_record.weight or 0
                    )
                except (TypeError, ValueError):
                    weight_changed = record.get("weight") != db_record.weight

            if target_changed or archive_changed or weight_changed:
                for order_uid in sorted(
                    {value for value in (current_order_uid, next_order_uid) if value}
                ):
                    ensure_order_receipt_unlocked(s, order_uid)

            now = time.strftime("%Y-%m-%d %H:%M")
            print(f"[update cargo] {db_record.packing_list_uid}")
            if db_record.packing_list_uid and int(db_record.status or 0) == 1:
                for locked_field in ("transfer_id", "waybill_id"):
                    if locked_field in record:
                        next_value = str(record.get(locked_field) or "").strip()
                        current_value = str(getattr(db_record, locked_field) or "").strip()
                        print(f"[update cargo] locked_field: {locked_field}, n: {next_value}, c: {current_value}")
                        if next_value != current_value:
                            raise ValueError("Outbound box waybill cannot be modified; undo shipment first")

            db_record.update_date = now
            for k, v in record.items():
                if k not in self._columns:
                    continue
                if v is None:
                    continue
                setattr(db_record, k, v)

            # If this row is used as a box, keep equivalent fields aligned.
            if db_record.packing_list_uid:
                if "count" in record and record.get("count") is not None:
                    db_record.piece_count = int(record.get("count"))
                if "real_en_name" in record and record.get("real_en_name") is not None:
                    db_record.item_name = record.get("real_en_name")
                if "piece_count" in record and record.get("piece_count") is not None:
                    db_record.count = int(record.get("piece_count"))
                if "item_name" in record and record.get("item_name") is not None:
                    db_record.real_en_name = record.get("item_name")

                if (
                    "waybill_id" in record
                    and str(db_record.waybill_id or "").strip()
                    and db_record.target_order_uid
                    and int(db_record.status or 0) != 1
                ):
                    ensure_order_revision_closed_for_downstream(
                        s, db_record.target_order_uid
                    )
                    db_record.status = 1
                    db_record.date = now
                    self._lock_box_cost(s, db_record, now)

            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    def archive(self, uid: str):
        s = SessionFactory()
        try:
            record = (
                s.query(self.table_class)
                .filter(self.table_class.uid == uid)
                .with_for_update()
                .first()
            )
            if record is None:
                return
            if record.target_order_uid:
                ensure_order_receipt_unlocked(s, record.target_order_uid)
            record.archive = True
            record.update_date = time.strftime("%Y-%m-%d %H:%M")
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    def delete(self, uid: str):
        s = SessionFactory()
        try:
            record = (
                s.query(self.table_class)
                .filter(self.table_class.uid == uid)
                .with_for_update()
                .first()
            )
            if record is None:
                return
            if record.target_order_uid:
                ensure_order_receipt_unlocked(s, record.target_order_uid)
            s.delete(record)
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()


# ---------------------------------------------------------------------------
# Module-level singletons
# ---------------------------------------------------------------------------

order_model = OrderModel(OrderTable)
cargo_model = CargoModel(CargoTable)


# ---------------------------------------------------------------------------
# Legacy helper
# ---------------------------------------------------------------------------


def get_data_point(field: str) -> dict:
    model = order_model if field == "order" else cargo_model
    records = model.read()
    return {r["uid"]: r for r in records}


class GoodsNameTable(Base):
    __tablename__ = "goods_names"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(256), nullable=False)
    lang = Column(String(16), nullable=False)
    category = Column(String(128), nullable=True)
    create_date = Column(String(32))
    update_date = Column(String(32))


class CustomsCodeTable(Base):
    __tablename__ = "customs_codes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(256), nullable=False)
    code = Column(String(64), nullable=False)
    create_date = Column(String(32))
    update_date = Column(String(32))


class ExcelTemplateTable(Base):
    __tablename__ = "excel_templates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    mode_key = Column(String(64), nullable=False, unique=True)
    label = Column(String(128), nullable=False)
    template_type = Column(String(32), nullable=False)
    config = Column(Text, nullable=False, default="{}")
    template_file = Column(String(256), nullable=True)
    single_order_only = Column(Boolean, default=False)
    requires_valid_quote = Column(Boolean, nullable=False, default=True)
    archive = Column(Boolean, default=False)
    create_date = Column(String(32))
    update_date = Column(String(32))


class TransportationModeTable(Base):
    __tablename__ = "transportation_modes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(128), nullable=False, unique=True)
    channel_group = Column(String(64), nullable=False, default="")
    cost = Column(Float, nullable=False, default=0)
    min_price = Column(Float, nullable=False, default=0)
    archive = Column(Boolean, default=False)
    create_date = Column(String(32))
    update_date = Column(String(32))


class TransportationCostVersionTable(Base):
    __tablename__ = "transportation_cost_versions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    transportation_mode_id = Column(Integer, ForeignKey("transportation_modes.id"), nullable=False)
    version_no = Column(Integer, nullable=False)
    name = Column(String(128), nullable=False)
    channel_group = Column(String(64), nullable=False, default="")
    cost = Column(Float, nullable=False, default=0)
    min_price = Column(Float, nullable=False, default=0)
    change_type = Column(String(32), nullable=False, default="update")
    remark = Column(String(512), nullable=True)
    operator_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    operator_name = Column(String(128), nullable=True)
    create_date = Column(String(32))


class BoxCostRecordTable(Base):
    __tablename__ = "box_cost_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    box_uid = Column(String(32), ForeignKey("cargos.uid"), nullable=False)
    packing_list_uid = Column(String(32), ForeignKey("packing_lists.uid"), nullable=True)
    order_uid = Column(String(32), ForeignKey("orders.uid"), nullable=True)
    transportation_mode_id = Column(Integer, ForeignKey("transportation_modes.id"), nullable=True)
    transportation_name = Column(String(128), nullable=False, default="")
    waybill_id = Column(String(256), nullable=False, default="")
    weight = Column(Float, nullable=False, default=0)
    unit_cost = Column(Float, nullable=False, default=0)
    total_cost = Column(Float, nullable=False, default=0)
    create_date = Column(String(32))


class OrderQuoteVersionTable(Base):
    __tablename__ = "order_quote_versions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    order_uid = Column(String(32), ForeignKey("orders.uid"), nullable=False)
    version_no = Column(Integer, nullable=False)
    transportation_mode_id = Column(Integer, ForeignKey("transportation_modes.id"), nullable=True)
    transportation_name = Column(String(128), nullable=False, default="")
    channel_cost = Column(Float, nullable=False, default=0)
    min_price = Column(Float, nullable=False, default=0)
    unit_price = Column(Numeric(14, 4), nullable=False, default=0)
    surcharge = Column(Numeric(14, 2), nullable=False, default=0)
    weight_snapshot = Column(Numeric(14, 3), nullable=False, default=0)
    billing_weight_snapshot = Column(Numeric(14, 3), nullable=False, default=0)
    receivable_amount = Column(Numeric(14, 2), nullable=False, default=0)
    quoted_price = Column(Float, nullable=False, default=0)
    status = Column(String(32), nullable=False, default="adopted")
    is_final = Column(Boolean, nullable=False, default=False)
    quote_remark = Column(String(512), nullable=True)
    review_remark = Column(String(512), nullable=True)
    quoter_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    quoter_name = Column(String(128), nullable=True)
    reviewer_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    reviewer_name = Column(String(128), nullable=True)
    create_date = Column(String(32))
    review_date = Column(String(32), nullable=True)
    effective_date = Column(String(32), nullable=True)


class PaymentReceiptTable(Base):
    __tablename__ = "payment_receipts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    receipt_no = Column(String(32), nullable=True, unique=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    customer_name = Column(String(256), nullable=False)
    receipt_date = Column(String(10), nullable=False)
    payment_method = Column(String(32), nullable=False)
    remark = Column(String(512), nullable=True)
    status = Column(String(32), nullable=False, default="pending")
    settlement_status = Column(String(16), nullable=True)
    creator_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    creator_name = Column(String(128), nullable=False)
    reviewer_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    reviewer_name = Column(String(128), nullable=True)
    review_remark = Column(String(512), nullable=True)
    review_date = Column(String(32), nullable=True)
    create_date = Column(String(32), nullable=False)
    update_date = Column(String(32), nullable=False)


class PaymentReceiptItemTable(Base):
    __tablename__ = "payment_receipt_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    receipt_id = Column(Integer, ForeignKey("payment_receipts.id"), nullable=False)
    order_uid = Column(String(32), ForeignKey("orders.uid"), nullable=False)
    order_id = Column(String(128), nullable=False)
    receivable_snapshot = Column(Numeric(14, 2), nullable=False)
    received_before = Column(Numeric(14, 2), nullable=False, default=0)
    amount = Column(Numeric(14, 2), nullable=False)
    remaining_after = Column(Numeric(14, 2), nullable=False)
    settlement_difference = Column(Numeric(14, 2), nullable=True)


class OrderReceiptRevisionTable(Base):
    """管理员为已有收据的订单开启的受控修订窗口。"""

    __tablename__ = "order_receipt_revisions"
    __table_args__ = (
        Index("idx_order_receipt_revisions_order_status", "order_uid", "status"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    order_uid = Column(String(32), ForeignKey("orders.uid"), nullable=False)
    status = Column(String(16), nullable=False, default="open")
    reason = Column(String(512), nullable=False)
    opened_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    opened_by_name = Column(String(128), nullable=False)
    opened_at = Column(String(32), nullable=False)
    closed_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    closed_by_name = Column(String(128), nullable=True)
    closed_at = Column(String(32), nullable=True)
    close_type = Column(String(32), nullable=True)
    close_remark = Column(String(512), nullable=True)
    closing_receipt_id = Column(
        Integer, ForeignKey("payment_receipts.id"), nullable=True
    )


def order_has_receipt_history(session, order_uid: str) -> bool:
    """订单是否曾出现在任意收款单明细中。"""
    if not order_uid:
        return False
    return (
        session.query(PaymentReceiptItemTable.id)
        .filter(PaymentReceiptItemTable.order_uid == order_uid)
        .first()
        is not None
    )


def get_open_order_receipt_revision(session, order_uid: str, for_update=False):
    """读取订单当前开放的收据修订窗口。"""
    if not order_uid:
        return None
    query = session.query(OrderReceiptRevisionTable).filter(
        OrderReceiptRevisionTable.order_uid == order_uid,
        OrderReceiptRevisionTable.status == "open",
    )
    if for_update:
        query = query.with_for_update()
    return query.order_by(OrderReceiptRevisionTable.id.desc()).first()


def order_receipt_locked(session, order_uid: str) -> bool:
    """有收据历史且没有管理员开放的修订窗口时，计费基础锁定。"""
    return bool(
        order_has_receipt_history(session, order_uid)
        and get_open_order_receipt_revision(session, order_uid) is None
    )


def ensure_order_receipt_unlocked(session, order_uid: str, order=None):
    """
    锁定订单行并校验收据锁，与收据创建共用同一并发边界。
    """
    locked_order = order
    if locked_order is None:
        locked_order = (
            session.query(OrderTable)
            .filter(OrderTable.uid == order_uid)
            .with_for_update()
            .first()
        )
    if locked_order is None:
        raise LookupError("订单不存在")
    if order_receipt_locked(session, order_uid):
        raise ReceiptLockedError()
    return locked_order


def ensure_order_without_receipt_history(session, order_uid: str, order=None):
    """归档或删除订单时，收据历史永远不可被修订窗口绕过。"""
    locked_order = order
    if locked_order is None:
        locked_order = (
            session.query(OrderTable)
            .filter(OrderTable.uid == order_uid)
            .with_for_update()
            .first()
        )
    if locked_order is None:
        raise LookupError("订单不存在")
    if order_has_receipt_history(session, order_uid):
        raise ReceiptLockedError()
    return locked_order


def ensure_order_revision_closed_for_downstream(session, order_uid: str):
    """修订期间禁止创建出库、成本或奖金等新的下游快照。"""
    if not order_uid:
        return
    # 与开启/关闭修订、生成收款单共用订单行锁，避免“检查后出库”竞态。
    (
        session.query(OrderTable.uid)
        .filter(OrderTable.uid == order_uid)
        .with_for_update()
        .first()
    )
    if get_open_order_receipt_revision(session, order_uid) is not None:
        raise OrderRevisionOpenError()


class SalesFollowupBonusRateTable(Base):
    __tablename__ = "sales_followup_bonus_rates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    rate_per_kg = Column(Numeric(14, 4), nullable=False)
    effective_from = Column(String(10), nullable=False, unique=True)
    remark = Column(String(512), nullable=True)
    creator_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    creator_name = Column(String(128), nullable=True)
    create_date = Column(String(32), nullable=False)


class AuditLogTable(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_type = Column(String(64), nullable=False)
    target_type = Column(String(64), nullable=False)
    target_id = Column(String(128), nullable=True)
    action = Column(String(64), nullable=False)
    operator_id = Column(Integer, nullable=True)
    operator_name = Column(String(128), nullable=True)
    operator_role = Column(String(128), nullable=True)
    before_data = Column(Text, nullable=True)
    after_data = Column(Text, nullable=True)
    remark = Column(String(512), nullable=True)
    ip = Column(String(64), nullable=True)
    create_date = Column(String(32))
