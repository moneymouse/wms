import time
import json

from sqlalchemy import Column, String, Integer, Enum as SAEnum
from sqlalchemy.orm import relationship
from sqlalchemy.orm import Mapped
from data.database import Base, SessionFactory
from data.user.Role import user_roles
import logging
from typing import List

ROLES = ["admin", "store_manager", "salesperson", "clerk", "finance", "worker"]

STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"


class UserTable(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    phone = Column(String(32), nullable=False, unique=True)
    name = Column(String(128), nullable=False)
    password = Column(String(512), nullable=False)
    status = Column(
        SAEnum("pending", "approved", "rejected"), nullable=False, default="pending"
    )
    remark = Column(String(256), default=None)
    create_date = Column(String(32))
    update_date = Column(String(32))

    roles: Mapped[List["RoleTable"]] = relationship("RoleTable", secondary=user_roles, back_populates="users")

    def to_dict(self, include_password=False):
        role_names = [r.name for r in self.roles] if self.roles else []
        d = {
            "id": self.id,
            "phone": self.phone,
            "name": self.name,
            "role": role_names[0] if role_names else None,
            "roles": role_names,
            "status": self.status,
            "remark": self.remark,
            "create_date": self.create_date,
            "update_date": self.update_date,
        }
        if include_password:
            d["password"] = self.password
        return d


class UserModel:
    def create(self, phone: str, name: str, password_hash: str):
        now = time.strftime("%Y-%m-%d %H:%M")
        with SessionFactory() as session:
            user = UserTable(
                phone=phone,
                name=name,
                password=password_hash,
                status="pending",
                create_date=now,
                update_date=now,
            )
            session.add(user)
            session.commit()
            session.refresh(user)
            return user.to_dict()

    def get_by_phone(self, phone: str, include_password: bool = False):
        with SessionFactory() as session:
            user = session.query(UserTable).filter_by(phone=phone).first()
            return user.to_dict(include_password=include_password) if user else None

    def get_by_id(self, user_id: int):
        with SessionFactory() as session:
            user = session.query(UserTable).filter_by(id=user_id).first()
            return user.to_dict() if user else None

    def get_all(self, exclude_rejected: bool = True):
        with SessionFactory() as session:
            query = session.query(UserTable)
            if exclude_rejected:
                query = query.filter(UserTable.status != "rejected")
            users = query.all()
            return [u.to_dict() for u in users]

    def get_by_status(self, status: str):
        with SessionFactory() as session:
            users = session.query(UserTable).filter_by(status=status).all()
            return [u.to_dict() for u in users]

    def get_by_role(self, role_name: str):
        from data.user.Role import RoleTable, user_roles
        with SessionFactory() as session:
            users = (
                session.query(UserTable)
                .join(user_roles, UserTable.id == user_roles.c.user_id)
                .join(RoleTable, RoleTable.id == user_roles.c.role_id)
                .filter(RoleTable.name == role_name)
                .filter(UserTable.status == STATUS_APPROVED)
                .all()
            )
            return [u.to_dict() for u in users]

    def approve(self, user_id: int, role_objects=None):
        now = time.strftime("%Y-%m-%d %H:%M")
        with SessionFactory() as session:
            user = session.query(UserTable).filter_by(id=user_id).first()
            if user is None:
                return None
            user.status = "approved"
            if role_objects is not None:
                user.roles = [session.merge(r) for r in role_objects]
            user.update_date = now
            session.commit()
            return user.to_dict()

    def reject(self, user_id: int, remark: str = None):
        now = time.strftime("%Y-%m-%d %H:%M")
        with SessionFactory() as session:
            user = session.query(UserTable).filter_by(id=user_id).first()
            if user is None:
                return None
            user.status = "rejected"
            user.remark = remark
            user.update_date = now
            session.commit()
            return user.to_dict()

    def update_role(self, user_id: int, role_objects=None):
        now = time.strftime("%Y-%m-%d %H:%M")
        with SessionFactory() as session:
            user = session.query(UserTable).filter_by(id=user_id).first()
            if user is None:
                return None
            if role_objects is not None:
                user.roles = [session.merge(r) for r in role_objects]
            else:
                user.roles = []
            user.update_date = now
            session.commit()
            return user.to_dict()

    def update_password(self, user_id: int, new_password_hash: str):
        """更新用户密码"""
        now = time.strftime("%Y-%m-%d %H:%M")
        with SessionFactory() as session:
            user = session.query(UserTable).filter_by(id=user_id).first()
            if user is None:
                return None
            user.password = new_password_hash
            user.update_date = now
            session.commit()
            return user.to_dict()

    def get_by_id_with_password(self, user_id: int):
        """获取用户信息，包含密码哈希"""
        with SessionFactory() as session:
            user = session.query(UserTable).filter_by(id=user_id).first()
            return user.to_dict(include_password=True) if user else None

    def delete(self, user_id: int) -> bool:
        """硬删除用户，并清理关联引用。"""
        with SessionFactory() as session:
            user = session.query(UserTable).filter_by(id=user_id).first()
            if user is None:
                return False

            from data.DB import (
                CargoTable,
                OrderReceiptRevisionTable,
                OrderQuoteVersionTable,
                OrderTable,
                PaymentReceiptTable,
                SalesFollowupBonusRateTable,
            )
            from data.packing.PackingList import PackingListTable, BoxWorkerTable
            from data.user.PasswordResetRequest import PasswordResetRequestTable
            from data.finance.BonusItem import BonusItemTable
            from data.finance.BonusRate import BonusRateTable

            session.query(OrderTable).filter(OrderTable.salesman_id == user_id).update(
                {"salesman_id": None}, synchronize_session=False
            )
            session.query(CargoTable).filter(
                CargoTable.bonus_assigned_by == user_id
            ).update({"bonus_assigned_by": None}, synchronize_session=False)
            session.query(BonusItemTable).filter(
                BonusItemTable.updated_by == user_id
            ).update({"updated_by": None}, synchronize_session=False)
            session.query(BonusRateTable).filter(
                BonusRateTable.updated_by == user_id
            ).update({"updated_by": None}, synchronize_session=False)
            session.query(OrderQuoteVersionTable).filter(
                OrderQuoteVersionTable.quoter_id == user_id
            ).update({"quoter_id": None}, synchronize_session=False)
            session.query(OrderQuoteVersionTable).filter(
                OrderQuoteVersionTable.reviewer_id == user_id
            ).update({"reviewer_id": None}, synchronize_session=False)
            session.query(PaymentReceiptTable).filter(
                PaymentReceiptTable.creator_id == user_id
            ).update({"creator_id": None}, synchronize_session=False)
            session.query(PaymentReceiptTable).filter(
                PaymentReceiptTable.reviewer_id == user_id
            ).update({"reviewer_id": None}, synchronize_session=False)
            session.query(OrderReceiptRevisionTable).filter(
                OrderReceiptRevisionTable.opened_by_id == user_id
            ).update({"opened_by_id": None}, synchronize_session=False)
            session.query(OrderReceiptRevisionTable).filter(
                OrderReceiptRevisionTable.closed_by_id == user_id
            ).update({"closed_by_id": None}, synchronize_session=False)
            session.query(SalesFollowupBonusRateTable).filter(
                SalesFollowupBonusRateTable.creator_id == user_id
            ).update({"creator_id": None}, synchronize_session=False)

            session.query(BoxWorkerTable).filter(
                BoxWorkerTable.worker_id == user_id
            ).delete(synchronize_session=False)
            session.query(PasswordResetRequestTable).filter(
                PasswordResetRequestTable.user_id == user_id
            ).delete(synchronize_session=False)

            packing_list_uids = [
                uid
                for (uid,) in session.query(PackingListTable.uid)
                .filter(PackingListTable.creator_id == user_id)
                .all()
            ]
            if packing_list_uids:
                session.query(CargoTable).filter(
                    CargoTable.packing_list_uid.in_(packing_list_uids)
                ).update({"packing_list_uid": None}, synchronize_session=False)
                session.query(PackingListTable).filter(
                    PackingListTable.creator_id == user_id
                ).delete(synchronize_session=False)

            session.delete(user)
            session.commit()
            return True


user_model = UserModel()
