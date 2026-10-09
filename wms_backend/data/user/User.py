import time
import json

from sqlalchemy import Column, String, Integer, Enum as SAEnum, or_
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
                BoxCostRecordTable,
                OrderReceiptRevisionTable,
                OrderQuoteVersionTable,
                OrderTable,
                PaymentReceiptTable,
                SalesFollowupBonusRateTable,
            )
            from data.packing.PackingList import PackingListTable, BoxWorkerTable
            from data.intake import IntakeTable
            from data.user.PasswordResetRequest import PasswordResetRequestTable
            from data.finance.BonusItem import BonusItemTable
            from data.finance.BonusRate import BonusRateTable
            from data.customer.Customer import CustomerTable

            if (
                session.query(IntakeTable.uid)
                .outerjoin(PackingListTable, PackingListTable.uid == IntakeTable.packing_list_uid)
                .filter(or_(
                    IntakeTable.submitted_by == user_id,
                    IntakeTable.confirmed_by == user_id,
                    PackingListTable.creator_id == user_id,
                ))
                .first()
                is not None
            ):
                from services.order_edit_policy import OrderEditConflictError

                raise OrderEditConflictError("该账号关联纸单来源或核对记录，不能硬删除，请保留操作人员身份")

            salesman_order_uids = {
                row[0]
                for row in session.query(OrderTable.uid)
                .filter(OrderTable.salesman_id == user_id)
                .all()
            }
            worker_order_uids = {
                row[0]
                for row in session.query(CargoTable.target_order_uid)
                .join(BoxWorkerTable, BoxWorkerTable.box_uid == CargoTable.uid)
                .filter(
                    BoxWorkerTable.worker_id == user_id,
                    CargoTable.target_order_uid.isnot(None),
                )
                .all()
            }
            packing_list_uids = [
                uid
                for (uid,) in session.query(PackingListTable.uid)
                .filter(PackingListTable.creator_id == user_id)
                .all()
            ]
            worker_box_uids = {
                row[0]
                for row in session.query(BoxWorkerTable.box_uid)
                .filter(BoxWorkerTable.worker_id == user_id)
                .all()
            }
            packing_box_uids = set()
            if packing_list_uids:
                packing_box_uids = {
                    row[0]
                    for row in session.query(CargoTable.uid)
                    .filter(CargoTable.packing_list_uid.in_(packing_list_uids))
                    .all()
                }
            candidate_box_uids = sorted(worker_box_uids | packing_box_uids)
            candidate_box_state = {
                row.uid: (row.target_order_uid, row.packing_list_uid)
                for row in session.query(
                    CargoTable.uid,
                    CargoTable.target_order_uid,
                    CargoTable.packing_list_uid,
                )
                .filter(CargoTable.uid.in_(candidate_box_uids))
                .all()
            }
            packing_order_uids = set()
            if packing_list_uids:
                packing_order_uids = {
                    row[0]
                    for row in session.query(CargoTable.target_order_uid)
                    .filter(
                        CargoTable.packing_list_uid.in_(packing_list_uids),
                        CargoTable.target_order_uid.isnot(None),
                    )
                    .all()
                }
            affected_order_uids = sorted(
                salesman_order_uids | worker_order_uids | packing_order_uids
            )
            if affected_order_uids:
                (
                    session.query(OrderTable.uid)
                    .filter(OrderTable.uid.in_(affected_order_uids))
                    .order_by(OrderTable.uid.asc())
                    .with_for_update()
                    .all()
                )
            locked_boxes = (
                session.query(CargoTable)
                .filter(CargoTable.uid.in_(candidate_box_uids))
                .order_by(CargoTable.uid.asc())
                .populate_existing()
                .with_for_update()
                .all()
                if candidate_box_uids
                else []
            )
            if any(
                (box.target_order_uid, box.packing_list_uid)
                != candidate_box_state.get(box.uid)
                for box in locked_boxes
            ) or len(locked_boxes) != len(candidate_box_state):
                from services.order_edit_policy import OrderEditConflictError

                raise OrderEditConflictError("箱子状态或归属已变化，请刷新后重试")
            if packing_list_uids:
                locked_packing_lists = (
                    session.query(PackingListTable)
                    .filter(PackingListTable.uid.in_(packing_list_uids))
                    .order_by(PackingListTable.uid.asc())
                    .populate_existing()
                    .with_for_update()
                    .all()
                )
                if len(locked_packing_lists) != len(packing_list_uids) or any(
                    packing_list.creator_id != user_id
                    for packing_list in locked_packing_lists
                ):
                    from services.order_edit_policy import OrderEditConflictError

                    raise OrderEditConflictError("装箱单已变化，请刷新后重试")
            from data.order_version import (
                new_correlation_id,
                record_mutation,
                snapshot_order,
            )

            before_by_order = {
                order_uid: snapshot_order(session, order_uid)
                for order_uid in affected_order_uids
            }

            session.query(OrderTable).filter(OrderTable.salesman_id == user_id).update(
                {"salesman_id": None}, synchronize_session=False
            )
            session.query(CustomerTable).filter(
                CustomerTable.created_by_id == user_id
            ).update({"created_by_id": None}, synchronize_session=False)
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

            if packing_list_uids:
                if (
                    session.query(BoxCostRecordTable.id)
                    .filter(BoxCostRecordTable.packing_list_uid.in_(packing_list_uids))
                    .first()
                    is not None
                ):
                    from services.order_edit_policy import (
                        OrderEditConflictError,
                    )

                    raise OrderEditConflictError("该账号仍是历史装箱单的创建人，不能硬删除该账号记录")
                session.query(CargoTable).filter(
                    CargoTable.packing_list_uid.in_(packing_list_uids)
                ).update({"packing_list_uid": None}, synchronize_session=False)
                session.query(PackingListTable).filter(
                    PackingListTable.creator_id == user_id
                ).delete(synchronize_session=False)

            session.delete(user)
            session.flush()
            # Bulk updates above bypass the identity map. Reload live rows before
            # deriving the after snapshots so salesman/box transitions are real.
            session.expire_all()
            correlation_id = new_correlation_id()
            for order_uid in affected_order_uids:
                record_mutation(
                    session,
                    order_uid,
                    before=before_by_order[order_uid],
                    after=snapshot_order(session, order_uid),
                    action="operator_removed",
                    summary="删除用户并清理订单关联",
                    correlation_id=correlation_id,
                )
            session.commit()
            return True


user_model = UserModel()
