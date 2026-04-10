import time

from sqlalchemy import Column, String, Integer, Enum as SAEnum
from data.database import Base, SessionFactory
import logging

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
    role = Column(String(32), default=None)
    status = Column(
        SAEnum("pending", "approved", "rejected"), nullable=False, default="pending"
    )
    remark = Column(String(256), default=None)
    create_date = Column(String(32))
    update_date = Column(String(32))

    def to_dict(self, include_password=False):
        d = {
            "id": self.id,
            "phone": self.phone,
            "name": self.name,
            "role": self.role,
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

    def approve(self, user_id: int, role: str):
        now = time.strftime("%Y-%m-%d %H:%M")
        with SessionFactory() as session:
            user = session.query(UserTable).filter_by(id=user_id).first()
            if user is None:
                return None
            user.status = "approved"
            user.role = role
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

    def update_role(self, user_id: int, role: str):
        now = time.strftime("%Y-%m-%d %H:%M")
        with SessionFactory() as session:
            user = session.query(UserTable).filter_by(id=user_id).first()
            if user is None:
                return None
            user.role = role
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


user_model = UserModel()
