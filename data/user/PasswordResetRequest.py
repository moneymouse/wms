import time

from sqlalchemy import Column, String, Integer, Enum as SAEnum, ForeignKey
from data.database import Base, SessionFactory


STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"


class PasswordResetRequestTable(Base):
    __tablename__ = "password_reset_requests"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    new_password_hash = Column(String(512), nullable=False)
    status = Column(
        SAEnum("pending", "approved", "rejected"), nullable=False, default="pending"
    )
    remark = Column(String(256), default=None)
    create_date = Column(String(32))
    update_date = Column(String(32))

    def to_dict(self):
        return {
            "id": self.id,
            "user_id": self.user_id,
            "status": self.status,
            "remark": self.remark,
            "create_date": self.create_date,
            "update_date": self.update_date,
        }


class PasswordResetRequestModel:
    def create(self, user_id: int, new_password_hash: str):
        """创建密码重置申请"""
        now = time.strftime("%Y-%m-%d %H:%M")
        with SessionFactory() as session:
            # 先取消该用户之前的待审核申请
            session.query(PasswordResetRequestTable).filter_by(
                user_id=user_id, status="pending"
            ).update(
                {"status": "rejected", "remark": "已被新申请替代", "update_date": now}
            )

            request = PasswordResetRequestTable(
                user_id=user_id,
                new_password_hash=new_password_hash,
                status="pending",
                create_date=now,
                update_date=now,
            )
            session.add(request)
            session.commit()
            session.refresh(request)
            return request.to_dict()

    def get_by_id(self, request_id: int):
        """根据ID获取申请"""
        with SessionFactory() as session:
            request = (
                session.query(PasswordResetRequestTable)
                .filter_by(id=request_id)
                .first()
            )
            return request.to_dict() if request else None

    def get_pending(self):
        """获取所有待审核的申请"""
        with SessionFactory() as session:
            requests = (
                session.query(PasswordResetRequestTable)
                .filter_by(status="pending")
                .all()
            )
            return [r.to_dict() for r in requests]

    def get_pending_with_user_info(self):
        """获取所有待审核的申请，包含用户信息"""
        from data.user.User import UserTable

        with SessionFactory() as session:
            results = (
                session.query(PasswordResetRequestTable, UserTable)
                .join(UserTable, PasswordResetRequestTable.user_id == UserTable.id)
                .filter(PasswordResetRequestTable.status == "pending")
                .all()
            )

            return [
                {
                    "id": req.id,
                    "user_id": req.user_id,
                    "user_name": user.name,
                    "user_phone": user.phone,
                    "status": req.status,
                    "create_date": req.create_date,
                }
                for req, user in results
            ]

    def approve(self, request_id: int):
        """审核通过申请，返回申请信息（包含新密码哈希）"""
        now = time.strftime("%Y-%m-%d %H:%M")
        with SessionFactory() as session:
            request = (
                session.query(PasswordResetRequestTable)
                .filter_by(id=request_id)
                .first()
            )
            if request is None:
                return None
            if request.status != "pending":
                return None

            request.status = "approved"
            request.update_date = now
            session.commit()

            return {
                "id": request.id,
                "user_id": request.user_id,
                "new_password_hash": request.new_password_hash,
                "status": request.status,
            }

    def reject(self, request_id: int, remark: str = None):
        """拒绝申请"""
        now = time.strftime("%Y-%m-%d %H:%M")
        with SessionFactory() as session:
            request = (
                session.query(PasswordResetRequestTable)
                .filter_by(id=request_id)
                .first()
            )
            if request is None:
                return None
            if request.status != "pending":
                return None

            request.status = "rejected"
            request.remark = remark
            request.update_date = now
            session.commit()
            return request.to_dict()


password_reset_request_model = PasswordResetRequestModel()
