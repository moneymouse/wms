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


class CargoOutboundRecordTable(Base):
    """Append-only registration facts; actual occurrence may be unknown."""
    __tablename__ = "cargo_outbound_records"
    id = Column(Integer, primary_key=True, autoincrement=True)
    # Historical identifiers intentionally survive existing hard-delete paths.
    cargo_uid = Column(String(32), nullable=False, index=True)
    order_uid = Column(String(32), nullable=False)
    occurred_at = Column(String(32), nullable=True)
    recorded_at = Column(String(32), nullable=False)
    source = Column(String(64), nullable=False)
    operator_id = Column(Integer, nullable=True)
    operator_name = Column(String(128), nullable=True)


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
    UPDATE_FIELDS = {
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

    def create(self, record: dict) -> str:
        """Create an order and its complete V1 in one transaction."""
        uid = str(int(time.time() * 1000000)) + str(random.randint(10, 99))
        db_dict = {k: v for k, v in record.items() if k in self._columns}
        db_dict["uid"] = uid
        db_dict["create_date"] = time.strftime("%Y-%m-%d %H:%M")
        customer_id = record.get("customer_id")

        s = SessionFactory()
        try:
            db_record = OrderTable(**db_dict)
            if customer_id not in (None, "", 0, "0"):
                from data.customer.Customer import CustomerTable

                customer = (
                    s.query(CustomerTable)
                    .filter(CustomerTable.id == int(customer_id))
                    .first()
                )
                if customer is None:
                    raise ValueError(f"Customer {customer_id} not found")
                db_record.customers = [customer]
            s.add(db_record)
            s.flush()
            from data.order_version import create_order_version, snapshot_order

            create_order_version(s, uid, snapshot_order(s, uid))
            s.commit()
            return uid
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    def update(self, uid: str, record: dict):
        """Update an order under a database row lock and append one delta."""
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
            from data.order_version import record_mutation, snapshot_order

            before = snapshot_order(s, uid)
            changed_fields = {
                key
                for key, value in record.items()
                if key in self.UPDATE_FIELDS
                and key != "update_date"
                and value is not None
                and getattr(db_record, key) != value
            }
            if changed_fields:
                for key in changed_fields:
                    setattr(db_record, key, record[key])
                db_record.update_date = time.strftime("%Y-%m-%d %H:%M")
            s.flush()
            after = snapshot_order(s, uid)
            record_mutation(
                s,
                uid,
                before=before,
                after=after,
                action="order_updated",
                summary="修改订单信息",
            )
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    @staticmethod
    def _archive_related_records(session, order_uids: list[str], now: str) -> set[str]:
        """Soft-archive order-owned operational and financial rows atomically."""
        normalized = sorted({str(uid) for uid in order_uids if uid})
        if not normalized:
            return set()

        changed_order_uids: set[str] = set()
        cargos = (
            session.query(CargoTable)
            .filter(CargoTable.target_order_uid.in_(normalized))
            .order_by(CargoTable.target_order_uid.asc(), CargoTable.uid.asc())
            .with_for_update()
            .all()
        )
        for cargo in cargos:
            if not cargo.archive:
                cargo.archive = True
                cargo.update_date = now
                changed_order_uids.add(cargo.target_order_uid)

        financial_models = (
            BoxCostRecordTable,
            OrderQuoteVersionTable,
            OrderPriceAdjustmentTable,
            PaymentReceiptItemTable,
        )
        for model in financial_models:
            rows = (
                session.query(model)
                .filter(model.order_uid.in_(normalized))
                .order_by(model.order_uid.asc(), model.id.asc())
                .with_for_update()
                .all()
            )
            for row in rows:
                if not row.archive:
                    row.archive = True
                    changed_order_uids.add(row.order_uid)

        return changed_order_uids

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
            from data.order_version import record_mutation, snapshot_order

            before = snapshot_order(s, uid)
            now = time.strftime("%Y-%m-%d %H:%M")
            order.archive = True
            order.update_date = now
            self._archive_related_records(s, [uid], now)
            s.flush()
            record_mutation(
                s,
                uid,
                before=before,
                after=snapshot_order(s, uid),
                action="order_archived",
                summary="归档订单及关联箱子/财务信息",
            )
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

            from data.order_version import record_mutation, snapshot_order

            before = snapshot_order(s, uid)
            retain_history = order_requires_archival(s, uid)
            if retain_history:
                now = time.strftime("%Y-%m-%d %H:%M")
                order.archive = True
                order.update_date = now
                self._archive_related_records(s, [uid], now)
            record_mutation(
                s,
                uid,
                before=before,
                after=None,
                action="order_deleted",
                summary="删除订单",
            )
            if not retain_history:
                s.delete(order)
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    def archive_many(self, uids: list[str]) -> list[str]:
        """Atomically archive orders in UID lock order with one correlation id."""
        normalized = sorted({str(uid) for uid in uids if uid})
        if not normalized:
            return []
        s = SessionFactory()
        try:
            orders = (
                s.query(OrderTable)
                .filter(OrderTable.uid.in_(normalized))
                .order_by(OrderTable.uid.asc())
                .with_for_update()
                .all()
            )
            from data.order_version import (
                new_correlation_id,
                record_mutation,
                snapshot_order,
            )

            before = {order.uid: snapshot_order(s, order.uid) for order in orders}
            now = time.strftime("%Y-%m-%d %H:%M")
            changed = set()
            for order in orders:
                if not order.archive:
                    order.archive = True
                    order.update_date = now
                    changed.add(order.uid)
            changed.update(
                self._archive_related_records(
                    s, [order.uid for order in orders], now
                )
            )
            s.flush()
            correlation_id = new_correlation_id()
            for order_uid in sorted(changed):
                record_mutation(
                    s,
                    order_uid,
                    before=before[order_uid],
                    after=snapshot_order(s, order_uid),
                    action="order_archived",
                    summary="批量归档订单及关联箱子/财务信息",
                    correlation_id=correlation_id,
                )
            s.commit()
            return sorted(changed)
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    def delete_many(self, uids: list[str]) -> list[str]:
        """Delete orders, retaining referenced rows as archived history."""
        normalized = sorted({str(uid) for uid in uids if uid})
        if not normalized:
            return []
        s = SessionFactory()
        try:
            orders = (
                s.query(OrderTable)
                .filter(OrderTable.uid.in_(normalized))
                .order_by(OrderTable.uid.asc())
                .with_for_update()
                .all()
            )
            from data.order_version import (
                new_correlation_id,
                record_mutation,
                snapshot_order,
            )


            before = {order.uid: snapshot_order(s, order.uid) for order in orders}
            correlation_id = new_correlation_id()
            deleted_uids = [order.uid for order in orders]
            for order in orders:
                retain_history = order_requires_archival(s, order.uid)
                if retain_history:
                    now = time.strftime("%Y-%m-%d %H:%M")
                    order.archive = True
                    order.update_date = now
                    self._archive_related_records(s, [order.uid], now)
                record_mutation(
                    s,
                    order.uid,
                    before=before[order.uid],
                    after=None,
                    action="order_deleted",
                    summary="批量删除订单",
                    correlation_id=correlation_id,
                )
                if not retain_history:
                    s.delete(order)
            s.commit()
            return deleted_uids
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    def set_salesman(self, order_uid: str, user_id: int) -> bool:
        """Set the salesman for an order."""
        s = SessionFactory()
        try:
            order = (
                s.query(OrderTable)
                .filter(OrderTable.uid == order_uid)
                .with_for_update()
                .first()
            )
            if order is None:
                return False
            from data.order_version import record_mutation, snapshot_order

            before = snapshot_order(s, order_uid)
            order.salesman_id = user_id
            order.update_date = time.strftime("%Y-%m-%d %H:%M")
            s.flush()
            record_mutation(
                s,
                order_uid,
                before=before,
                after=snapshot_order(s, order_uid),
                action="salesman_updated",
                summary="修改业务员",
            )
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
            order = (
                s.query(OrderTable)
                .filter(OrderTable.uid == order_uid)
                .with_for_update()
                .first()
            )
            if order is None:
                return False
            from data.order_version import record_mutation, snapshot_order

            before = snapshot_order(s, order_uid)
            order.salesman_id = None
            order.update_date = time.strftime("%Y-%m-%d %H:%M")
            s.flush()
            record_mutation(
                s,
                order_uid,
                before=before,
                after=snapshot_order(s, order_uid),
                action="salesman_updated",
                summary="移除业务员",
            )
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
            order = (
                s.query(OrderTable)
                .filter(OrderTable.uid == order_uid)
                .with_for_update()
                .first()
            )
            if order is None:
                return False
            customer = (
                s.query(CustomerTable).filter(CustomerTable.id == customer_id).first()
            )
            if customer is None:
                return False
            if customer not in order.customers:
                from data.order_version import record_mutation, snapshot_order

                before = snapshot_order(s, order_uid)
                order.customers.append(customer)
                order.update_date = time.strftime("%Y-%m-%d %H:%M")
                s.flush()
                record_mutation(
                    s,
                    order_uid,
                    before=before,
                    after=snapshot_order(s, order_uid),
                    action="customer_updated",
                    summary="修改客户归属",
                )
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
            order = (
                s.query(OrderTable)
                .filter(OrderTable.uid == order_uid)
                .with_for_update()
                .first()
            )
            if order is None:
                return False
            customer = (
                s.query(CustomerTable).filter(CustomerTable.id == customer_id).first()
            )
            if customer is None:
                return False
            if customer in order.customers:
                from data.order_version import record_mutation, snapshot_order

                before = snapshot_order(s, order_uid)
                order.customers.remove(customer)
                order.update_date = time.strftime("%Y-%m-%d %H:%M")
                s.flush()
                record_mutation(
                    s,
                    order_uid,
                    before=before,
                    after=snapshot_order(s, order_uid),
                    action="customer_updated",
                    summary="修改客户归属",
                )
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
            order = (
                s.query(OrderTable)
                .filter(OrderTable.uid == order_uid)
                .with_for_update()
                .first()
            )
            if order is None:
                return False
            customers = (
                s.query(CustomerTable).filter(CustomerTable.id.in_(customer_ids)).all()
            )
            current_ids = sorted(customer.id for customer in order.customers)
            next_ids = sorted(customer.id for customer in customers)
            if current_ids != next_ids:
                from data.order_version import record_mutation, snapshot_order

                before = snapshot_order(s, order_uid)
                order.customers = customers
                order.update_date = time.strftime("%Y-%m-%d %H:%M")
                s.flush()
                record_mutation(
                    s,
                    order_uid,
                    before=before,
                    after=snapshot_order(s, order_uid),
                    action="customer_updated",
                    summary="修改客户归属",
                )
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
    UPDATE_FIELDS = {
        "origin_id",
        "transfer_id",
        "tag",
        "count",
        "weight",
        "real_en_name",
        "price",
        "waybill_id",
        "item_name",
        "item_details",
        "remark",
        "box_number",
        "piece_count",
    }

    def _to_dict(self, record, _fields=None, except_fields=None) -> dict:
        result = super()._to_dict(record, _fields, except_fields)
        if (
            record.packing_list_uid
            and "identity_editable" not in (except_fields or [])
            and (not _fields or "identity_editable" in _fields)
        ):
            from sqlalchemy.orm import object_session
            from services.order_edit_policy import box_identity_editable

            result["identity_editable"] = box_identity_editable(
                object_session(record), record
            )
        return result

    def _lock_after_order(self, session, uid: str):
        """Resolve ownership without a lock, then lock order before cargo."""
        candidate = (
            session.query(self.table_class.uid, self.table_class.target_order_uid)
            .filter(self.table_class.uid == uid)
            .first()
        )
        if candidate is None:
            return None
        candidate_order_uid = candidate.target_order_uid
        if candidate_order_uid:
            (
                session.query(OrderTable.uid)
                .filter(OrderTable.uid == candidate_order_uid)
                .with_for_update()
                .first()
            )
        record = (
            session.query(self.table_class)
            .filter(self.table_class.uid == uid)
            .populate_existing()
            .with_for_update()
            .first()
        )
        if record is not None and record.target_order_uid != candidate_order_uid:
            raise ValueError("货物归属已变化，请刷新后重试")
        return record

    def create(self, record: dict) -> str:
        """Create a cargo and version it when it is immediately attached."""
        uid = str(int(time.time() * 1000000)) + str(random.randint(10, 99))
        db_dict = {k: v for k, v in record.items() if k in self._columns}
        now = time.strftime("%Y-%m-%d %H:%M")
        # Identifiers alone are not an outbound fact.
        if int(db_dict.get("status") or 0) != 0 or db_dict.get("date"):
            raise ValueError("出库状态和时间必须通过确认出库服务写入")
        db_dict["uid"] = uid
        db_dict["create_date"] = now
        order_uid = db_dict.get("target_order_uid")
        s = SessionFactory()
        try:
            before = None
            if order_uid:
                from data.order_version import record_mutation, snapshot_order

                order = (
                    s.query(OrderTable)
                    .filter(OrderTable.uid == order_uid)
                    .with_for_update()
                    .first()
                )
                if order is None:
                    raise LookupError("订单不存在")
                before = snapshot_order(s, order_uid)
            s.add(self.table_class(**db_dict))
            s.flush()
            if order_uid:
                record_mutation(
                    s,
                    order_uid,
                    before=before,
                    after=snapshot_order(s, order_uid),
                    action="cargo_added",
                    summary="新增货物",
                )
            s.commit()
            return uid
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    def _lock_box_cost(self, session, box, now: str):
        """Compatibility delegate to the outbound cost implementation."""
        from services.outbound_service import freeze_box_cost
        return freeze_box_cost(session, box, now)

    def unbind_from_order(self, uid: str) -> bool:
        """Detach a cargo from its order by clearing target_order_uid."""
        s = SessionFactory()
        try:
            db_record = self._lock_after_order(s, uid)
            if db_record is None:
                return False

            if db_record.target_order_uid:
                from data.order_version import record_mutation, snapshot_order

                order_uid = db_record.target_order_uid
                (
                    s.query(OrderTable.uid)
                    .filter(OrderTable.uid == order_uid)
                    .with_for_update()
                    .first()
                )
                before = snapshot_order(s, order_uid)
            else:
                order_uid = None
                before = None

            db_record.target_order_uid = None
            db_record.update_date = time.strftime("%Y-%m-%d %H:%M")

            # Non-outbound box should stay in pending-outbound when detached.
            from services.order_edit_policy import cargo_is_outbound_or_later

            if db_record.packing_list_uid and not cargo_is_outbound_or_later(db_record.status):
                db_record.status = 0
            s.flush()
            if order_uid:
                record_mutation(
                    s,
                    order_uid,
                    before=before,
                    after=snapshot_order(s, order_uid),
                    action="box_unassigned" if db_record.packing_list_uid else "cargo_unbound",
                    summary="解绑箱子" if db_record.packing_list_uid else "移除货物",
                )
            s.commit()
            return True
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    def update(self, uid: str, record: dict, *, session=None, record_version=True):
        """Update cargo and keep legacy box fields synchronized for unified rows."""
        owned_session = session is None
        s = SessionFactory() if owned_session else session
        try:
            db_record = self._lock_after_order(s, uid)
            if db_record is None:
                return
            record = dict(record or {})
            if db_record.packing_list_uid:
                if "transfer_id" in record and record["transfer_id"] is not None:
                    record["transfer_id"] = str(record["transfer_id"]).strip()
                if "box_number" in record and record["box_number"] is not None:
                    try:
                        record["box_number"] = int(record["box_number"])
                    except (TypeError, ValueError):
                        raise ValueError("box_number must be integer")
            if "item_details" in record:
                import json

                raw_details = record.get("item_details")
                if isinstance(raw_details, str):
                    try:
                        normalized_details = json.loads(raw_details)
                    except (TypeError, ValueError):
                        raise ValueError("item_details must be valid JSON array")
                elif isinstance(raw_details, list):
                    normalized_details = raw_details
                else:
                    raise ValueError("item_details must be a list")
                if not isinstance(normalized_details, list):
                    raise ValueError("item_details must be a list")
                try:
                    current_details = (
                        json.loads(db_record.item_details)
                        if db_record.item_details
                        else []
                    )
                except (TypeError, ValueError):
                    current_details = []
                record["item_details"] = (
                    db_record.item_details
                    if current_details == normalized_details
                    else json.dumps(normalized_details, ensure_ascii=False)
                )

            forbidden_changed = sorted(
                key
                for key, value in record.items()
                if key in self._columns
                and key not in self.UPDATE_FIELDS
                and key != "update_date"
                and value is not None
                and getattr(db_record, key) != value
            )
            if forbidden_changed:
                raise ValueError(
                    f"不允许修改字段: {', '.join(forbidden_changed)}"
                )

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
            from data.order_version import (
                new_correlation_id,
                record_mutation,
                snapshot_order,
            )
            from services.order_edit_policy import (
                cargo_is_outbound_or_later,
                ensure_box_identity_editable,
                ensure_outbound_weight_editable,
            )

            affected_uids = sorted(
                {value for value in (current_order_uid, next_order_uid) if value}
            )
            if affected_uids:
                (
                    s.query(OrderTable.uid)
                    .filter(OrderTable.uid.in_(affected_uids))
                    .order_by(OrderTable.uid.asc())
                    .with_for_update()
                    .all()
                )
            before_by_order = {
                order_uid: snapshot_order(s, order_uid) for order_uid in affected_uids
            }

            changed_fields = {
                key
                for key, value in record.items()
                if key in self.UPDATE_FIELDS
                and key != "update_date"
                and value is not None
                and getattr(db_record, key) != value
            }
            ensure_box_identity_editable(
                s, db_record, {key: record[key] for key in changed_fields}
            )
            if "weight" in changed_fields:
                ensure_outbound_weight_editable(
                    db_record.status,
                    current_weight=db_record.weight,
                    next_weight=record.get("weight"),
                )
            if (
                db_record.packing_list_uid
                and int(db_record.status or 0) == 1
                and "waybill_id" in changed_fields
                and not str(record.get("waybill_id") or "").strip()
            ):
                raise ValueError(
                    "已出库箱不能清空转单号；如需撤销出库请使用撤销出库操作"
                )

            now = time.strftime("%Y-%m-%d %H:%M")
            if changed_fields:
                db_record.update_date = now
                for k in changed_fields:
                    setattr(db_record, k, record[k])

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

            s.flush()
            correlation_id = new_correlation_id()
            action = "box_updated" if db_record.packing_list_uid else "cargo_updated"
            if target_changed:
                action = "box_assigned" if db_record.packing_list_uid and next_order_uid else "cargo_reassigned"
            for order_uid in affected_uids if record_version else []:
                record_mutation(
                    s,
                    order_uid,
                    before=before_by_order[order_uid],
                    after=snapshot_order(s, order_uid),
                    action=action,
                    summary="修改箱子" if db_record.packing_list_uid else "修改货物",
                    correlation_id=correlation_id,
                )
            if owned_session:
                s.commit()
            return True
        except Exception:
            if owned_session:
                s.rollback()
            raise
        finally:
            if owned_session:
                s.close()

    def archive(self, uid: str):
        s = SessionFactory()
        try:
            record = self._lock_after_order(s, uid)
            if record is None:
                return
            if record.target_order_uid:
                from data.order_version import record_mutation, snapshot_order

                order_uid = record.target_order_uid
                (
                    s.query(OrderTable.uid)
                    .filter(OrderTable.uid == order_uid)
                    .with_for_update()
                    .first()
                )
                before = snapshot_order(s, order_uid)
            else:
                order_uid, before = None, None
            record.archive = True
            record.update_date = time.strftime("%Y-%m-%d %H:%M")
            s.flush()
            if order_uid:
                record_mutation(
                    s,
                    order_uid,
                    before=before,
                    after=snapshot_order(s, order_uid),
                    action="box_archived" if record.packing_list_uid else "cargo_archived",
                    summary="归档箱子" if record.packing_list_uid else "归档货物",
                )
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    def delete(self, uid: str):
        s = SessionFactory()
        try:
            record = self._lock_after_order(s, uid)
            if record is None:
                return
            if record.target_order_uid:
                from data.order_version import record_mutation, snapshot_order

                order_uid = record.target_order_uid
                (
                    s.query(OrderTable.uid)
                    .filter(OrderTable.uid == order_uid)
                    .with_for_update()
                    .first()
                )
                before = snapshot_order(s, order_uid)
            else:
                order_uid, before = None, None
            is_box = bool(record.packing_list_uid)
            if cargo_requires_archival(s, uid):
                record.archive = True
                record.update_date = time.strftime("%Y-%m-%d %H:%M")
            else:
                if record.packing_list_uid:
                    from data.packing.PackingList import BoxWorkerTable

                    s.query(BoxWorkerTable).filter(
                        BoxWorkerTable.box_uid == uid
                    ).delete(synchronize_session=False)
                s.delete(record)
            s.flush()
            if order_uid:
                record_mutation(
                    s,
                    order_uid,
                    before=before,
                    after=snapshot_order(s, order_uid),
                    action="box_deleted" if is_box else "cargo_deleted",
                    summary="删除箱子" if is_box else "删除货物",
                )
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    def mutate_many(self, uids: list[str], operation: str) -> dict:
        """Archive, delete or unbind cargos atomically across sorted orders."""
        if operation not in {"archive", "delete", "unbind"}:
            raise ValueError("unsupported cargo batch operation")
        normalized = sorted({str(uid) for uid in uids if uid})
        result = {"success": [], "failed": []}
        if not normalized:
            return result
        s = SessionFactory()
        try:
            candidates = (
                s.query(CargoTable.uid, CargoTable.target_order_uid)
                .filter(CargoTable.uid.in_(normalized))
                .order_by(CargoTable.uid.asc())
                .all()
            )
            candidate_map = {uid: order_uid for uid, order_uid in candidates}
            affected_order_uids = sorted(
                {order_uid for order_uid in candidate_map.values() if order_uid}
            )
            if affected_order_uids:
                (
                    s.query(OrderTable.uid)
                    .filter(OrderTable.uid.in_(affected_order_uids))
                    .order_by(OrderTable.uid.asc())
                    .with_for_update()
                    .all()
                )
            records = (
                s.query(CargoTable)
                .filter(CargoTable.uid.in_(normalized))
                .order_by(CargoTable.uid.asc())
                .with_for_update()
                .all()
            )
            record_map = {record.uid: record for record in records}
            for record in records:
                if record.target_order_uid != candidate_map.get(record.uid):
                    raise ValueError("货物归属已变化，请刷新后重试")

            from data.order_version import (
                new_correlation_id,
                record_mutation,
                snapshot_order,
            )

            before = {
                order_uid: snapshot_order(s, order_uid)
                for order_uid in affected_order_uids
            }
            now = time.strftime("%Y-%m-%d %H:%M")
            for uid in normalized:
                record = record_map.get(uid)
                if record is None:
                    result["failed"].append({"uid": uid, "error": "Cargo not found"})
                    continue
                if operation == "archive":
                    if not record.archive:
                        record.archive = True
                        record.update_date = now
                elif operation == "unbind":
                    record.target_order_uid = None
                    record.update_date = now
                    from services.order_edit_policy import cargo_is_outbound_or_later

                    if record.packing_list_uid and not cargo_is_outbound_or_later(record.status):
                        record.status = 0
                else:
                    if cargo_requires_archival(s, uid):
                        record.archive = True
                        record.update_date = now
                        result["success"].append(uid)
                        continue
                    if record.packing_list_uid:
                        from data.packing.PackingList import BoxWorkerTable

                        s.query(BoxWorkerTable).filter(
                            BoxWorkerTable.box_uid == uid
                        ).delete(synchronize_session=False)
                    s.delete(record)
                result["success"].append(uid)
            s.flush()
            correlation_id = new_correlation_id()
            action = {
                "archive": "cargos_archived",
                "delete": "cargos_deleted",
                "unbind": "cargos_unbound",
            }[operation]
            summary = {
                "archive": "批量归档货物/箱子",
                "delete": "批量删除货物/箱子",
                "unbind": "批量解绑货物/箱子",
            }[operation]
            for order_uid in affected_order_uids:
                record_mutation(
                    s,
                    order_uid,
                    before=before[order_uid],
                    after=snapshot_order(s, order_uid),
                    action=action,
                    summary=summary,
                    correlation_id=correlation_id,
                )
            s.commit()
            return result
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
    archive = Column(Boolean, nullable=False, default=False)
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
    archive = Column(Boolean, nullable=False, default=False)


class OrderPriceAdjustmentTable(Base):
    """A pending receivable/refund task created by an effective re-quote."""

    __tablename__ = "order_price_adjustments"
    __table_args__ = (
        Index("idx_order_price_adjustments_order_status", "order_uid", "status"),
        Index("idx_order_price_adjustments_created", "create_date", "id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    order_uid = Column(String(32), ForeignKey("orders.uid"), nullable=False)
    previous_quote_id = Column(
        Integer, ForeignKey("order_quote_versions.id"), nullable=False
    )
    new_quote_id = Column(
        Integer, ForeignKey("order_quote_versions.id"), nullable=False, unique=True
    )
    old_receivable = Column(Numeric(14, 2), nullable=False)
    new_receivable = Column(Numeric(14, 2), nullable=False)
    delta_amount = Column(Numeric(14, 2), nullable=False)
    direction = Column(String(16), nullable=False)
    status = Column(String(16), nullable=False, default="pending")
    creator_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    creator_name = Column(String(128), nullable=False)
    create_date = Column(String(32), nullable=False)
    archive = Column(Boolean, nullable=False, default=False)


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
    __table_args__ = (
        Index("idx_payment_receipt_items_adjustment", "adjustment_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    receipt_id = Column(Integer, ForeignKey("payment_receipts.id"), nullable=False)
    order_uid = Column(String(32), ForeignKey("orders.uid"), nullable=False)
    adjustment_id = Column(
        Integer,
        ForeignKey("order_price_adjustments.id", name="fk_payment_receipt_items_adjustment"),
        nullable=True,
    )
    order_id = Column(String(128), nullable=False)
    receivable_snapshot = Column(Numeric(14, 2), nullable=False)
    received_before = Column(Numeric(14, 2), nullable=False, default=0)
    amount = Column(Numeric(14, 2), nullable=False)
    remaining_after = Column(Numeric(14, 2), nullable=False)
    settlement_difference = Column(Numeric(14, 2), nullable=True)
    archive = Column(Boolean, nullable=False, default=False)


class OrderReceiptRevisionTable(Base):
    """Historical revision records retained for existing database data."""

    __tablename__ = "order_receipt_revisions"
    __table_args__ = (
        Index("idx_order_receipt_revisions_order_status", "order_uid", "status"),
        Index(
            "idx_order_receipt_revisions_opened",
            "status",
            "opened_at",
            "id",
        ),
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


def cargo_requires_archival(session, cargo_uid: str) -> bool:
    """Retain a cargo row when an existing cost record references its identity."""
    return (
        session.query(BoxCostRecordTable.id)
        .filter(BoxCostRecordTable.box_uid == cargo_uid)
        .first()
        is not None
    )


def order_requires_archival(session, order_uid: str) -> bool:
    """Keep foreign-key targets for recorded history when deleting an order."""
    return any(
        session.query(model.id).filter(model.order_uid == order_uid).first()
        is not None
        for model in (
            BoxCostRecordTable,
            OrderQuoteVersionTable,
            OrderPriceAdjustmentTable,
            PaymentReceiptItemTable,
            OrderReceiptRevisionTable,
        )
    )


def order_fully_outbound(session, order_uid: str) -> bool:
    """Return whether every active packing-list box is outbound with a waybill.

    Ordinary cargo rows (``packing_list_uid is NULL``) are intentionally not
    part of this shipping state.  An order without any assigned active boxes is
    not considered outbound.
    """
    if not order_uid:
        return False
    boxes = (
        session.query(CargoTable.status, CargoTable.waybill_id)
        .filter(
            CargoTable.target_order_uid == order_uid,
            CargoTable.archive == False,  # noqa: E712
            CargoTable.packing_list_uid.isnot(None),
        )
        .all()
    )
    return bool(boxes) and all(
        int(status or 0) == 1 and bool(str(waybill_id or "").strip())
        for status, waybill_id in boxes
    )


def lock_order_for_update(session, order_uid: str, order=None):
    """Acquire the database row lock and confirm the order exists."""
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
    return locked_order


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
