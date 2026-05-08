from sqlalchemy import Column, Integer, String, Text, ForeignKey
from sqlalchemy.orm import relationship

from data.database import Base, SessionFactory

# ---------------------------------------------------------------------------
# Field list for receiver records (mirrors the original pickle structure)
# ---------------------------------------------------------------------------
fields = [
    "receiver",
    "receiver_phone",
    "mail",
    "country",
    "province",
    "city",
    "address",
    "zip_code",
]


# ---------------------------------------------------------------------------
# ORM table definitions
# ---------------------------------------------------------------------------


class CustomerTable(Base):
    __tablename__ = "customers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(256), unique=True, nullable=False)
    phone = Column(String(64))  # 客户联系电话（敏感字段）
    wechat = Column(String(128))  # 客户微信号（敏感字段）

    receivers = relationship(
        "ReceiverTable",
        back_populates="customer",
        foreign_keys="ReceiverTable.customer_id",
        lazy="select",
    )

    # Many-to-many relationship with orders
    orders = relationship(
        "OrderTable",
        secondary="order_customers",
        back_populates="customers",
        lazy="select",
    )


class ReceiverTable(Base):
    __tablename__ = "receivers"

    id = Column(Integer, primary_key=True, autoincrement=True)
    customer_id = Column(Integer, ForeignKey("customers.id"), nullable=False)
    receiver = Column(String(256))
    receiver_phone = Column(String(64))
    mail = Column(String(256))
    country = Column(String(128))
    province = Column(String(128))
    city = Column(String(128))
    address = Column(Text)
    zip_code = Column(String(64))

    customer = relationship(
        "CustomerTable",
        back_populates="receivers",
        foreign_keys=[customer_id],
    )


# ---------------------------------------------------------------------------
# Public API – function signatures are identical to the original pickle-based
# implementation so that all callers in app.py keep working unchanged.
# ---------------------------------------------------------------------------


def add_customer_record(record: dict) -> int | None:
    """Add a receiver under an existing customer, deduplicating by name + address.

    Note: This function does NOT create customers. Use POST /api/customer to create
    customers first. This only adds receiver info if the customer already exists.

    Returns:
        The customer ID if customer was found, None otherwise.
    """
    customer_name = str(record.get("customer_name", "")).strip()
    raw_customer_id = record.get("customer_id")
    receiver_name = str(record.get("receiver", "")).strip()
    address_val = str(record.get("address", "")).strip()

    customer_id = None
    if raw_customer_id not in [None, "", 0, "0"]:
        try:
            customer_id = int(raw_customer_id)
        except (TypeError, ValueError):
            return None

    if not customer_id and not customer_name:
        return None

    s = SessionFactory()
    try:
        # Find existing customer (do NOT create)
        if customer_id:
            customer = s.query(CustomerTable).filter_by(id=customer_id).first()
        else:
            customer = s.query(CustomerTable).filter_by(name=customer_name).first()
        if customer is None:
            return None

        customer_id = customer.id

        # Skip if no receiver info provided
        if not receiver_name:
            return customer_id

        # Dedup: skip if same receiver name + address already exists
        existing = (
            s.query(ReceiverTable)
            .filter_by(
                customer_id=customer_id, receiver=receiver_name, address=address_val
            )
            .first()
        )
        if existing:
            return customer_id

        new_receiver = ReceiverTable(
            customer_id=customer_id,
            **{k: str(record.get(k, "")).strip() for k in fields},
        )
        s.add(new_receiver)
        s.commit()
        return customer_id
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def get_customer_record(customer_id: int = 0, receiver_id: str = ""):
    """Return customer / receiver data matching the original pickle structure.

    - No args  → list of customer dicts with id and name
    - customer_id  → list of {receiver_id, receiver_name} dicts for that customer
    - receiver_id  → full receiver info dict
    """
    s = SessionFactory()
    try:
        if customer_id:
            receivers = s.query(ReceiverTable).filter_by(customer_id=customer_id).all()
            return [
                {"receiver_id": str(r.id), "receiver_name": r.receiver}
                for r in receivers
            ]

        if receiver_id:
            r = s.query(ReceiverTable).filter_by(id=int(receiver_id)).first()
            if r is None:
                return {}
            return {k: getattr(r, k) or "" for k in fields}

        # No args – return customer list with id and name
        customers = s.query(CustomerTable).all()
        return [{"name": c.name, "id": c.id} for c in customers]
    finally:
        s.close()


def list_customer_records(receiver_id: str = "") -> list:
    """Return all receivers that share the same receiver name as receiver_id."""
    if not receiver_id:
        return []

    s = SessionFactory()
    try:
        source = s.query(ReceiverTable).filter_by(id=int(receiver_id)).first()
        if source is None:
            return []
        same_name = s.query(ReceiverTable).filter_by(receiver=source.receiver).all()
        return [{k: getattr(r, k) or "" for k in fields} for r in same_name]
    finally:
        s.close()


def list_receiver_records(receiver_ids: list) -> list:
    """Return full receiver info dicts (with receiver_id key) for a list of ids."""
    if not receiver_ids:
        return []

    s = SessionFactory()
    try:
        result = []
        for rid in receiver_ids:
            r = s.query(ReceiverTable).filter_by(id=int(rid)).first()
            if r is None:
                continue
            entry = {k: getattr(r, k) or "" for k in fields}
            entry["receiver_id"] = str(r.id)
            result.append(entry)
        return result
    finally:
        s.close()


def del_receiver_record(customer_id: int = 0, receiver_id: str = ""):
    """Delete a single receiver record."""
    if not (customer_id and receiver_id):
        return

    s = SessionFactory()
    try:
        r = (
            s.query(ReceiverTable)
            .filter_by(customer_id=customer_id, id=int(receiver_id))
            .first()
        )
        if r:
            s.delete(r)
            s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def del_customer_record(customer_id: int = 0):
    """Delete a customer and all of their receiver records."""
    if not customer_id:
        return

    s = SessionFactory()
    try:
        # Cascade: delete receivers first
        s.query(ReceiverTable).filter_by(customer_id=customer_id).delete()
        customer = s.query(CustomerTable).filter_by(id=customer_id).first()
        if customer is None:
            s.commit()
            return
        s.delete(customer)
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


# ---------------------------------------------------------------------------
# save_customer_record is kept as a no-op for any remaining call sites.
# With SQLAlchemy the session commits are handled inside each function above.
# ---------------------------------------------------------------------------
def save_customer_record():
    pass


# ---------------------------------------------------------------------------
# 客户敏感信息管理函数（phone, wechat）
# ---------------------------------------------------------------------------

# 定义敏感字段
SENSITIVE_FIELDS = ["phone", "wechat"]
# 允许访问敏感字段的角色
ALLOWED_ROLES = ["admin", "store_manager", "salesperson"]


def filter_sensitive_fields(customer_data: dict, user_role: str = None) -> dict:
    """根据用户角色过滤客户数据中的敏感字段。

    Args:
        customer_data: 客户数据字典
        user_role: 用户角色，如果在ALLOWED_ROLES中则返回完整数据，否则过滤敏感字段

    Returns:
        过滤后的客户数据字典
    """
    if user_role in ALLOWED_ROLES:
        return customer_data

    # 移除敏感字段
    filtered_data = customer_data.copy()
    for field in SENSITIVE_FIELDS:
        filtered_data.pop(field, None)

    return filtered_data


def get_customer_detail(customer_id: int = 0, include_sensitive: bool = False) -> dict:
    """获取客户的详细信息，包括phone和wechat。

    Args:
        customer_id: 客户ID（主键，避免回表查询）
        include_sensitive: 是否包含敏感字段（由权限控制决定）

    Returns:
        客户详细信息字典，如果客户不存在返回空字典
    """
    if not customer_id:
        return {}

    s = SessionFactory()
    try:
        customer = s.query(CustomerTable).filter_by(id=customer_id).first()
        if customer is None:
            return {}

        result = {
            "id": customer.id,
            "name": customer.name,
        }

        if include_sensitive:
            result["phone"] = customer.phone or ""
            result["wechat"] = customer.wechat or ""

        return result
    finally:
        s.close()


def get_all_customers_detail(include_sensitive: bool = False) -> list:
    """获取所有客户的详细信息列表。

    Args:
        include_sensitive: 是否包含敏感字段（由权限控制决定）

    Returns:
        客户详细信息列表
    """
    s = SessionFactory()
    try:
        customers = s.query(CustomerTable).all()
        result = []
        for customer in customers:
            customer_data = {
                "id": customer.id,
                "name": customer.name,
            }
            if include_sensitive:
                customer_data["phone"] = customer.phone or ""
                customer_data["wechat"] = customer.wechat or ""
            result.append(customer_data)
        return result
    finally:
        s.close()


def update_customer_info(customer_id: int, phone: str = None, wechat: str = None):
    """更新客户的联系信息（phone和wechat）。

    Args:
        customer_id: 客户ID
        phone: 客户电话（可选）
        wechat: 客户微信（可选）
    """
    if not customer_id:
        return

    s = SessionFactory()
    try:
        customer = s.query(CustomerTable).filter_by(id=customer_id).first()
        if customer is None:
            return

        # 更新现有客户信息
        if phone is not None:
            customer.phone = phone.strip() if phone.strip() else None
        if wechat is not None:
            customer.wechat = wechat.strip() if wechat.strip() else None

        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()
