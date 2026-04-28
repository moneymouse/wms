from sqlalchemy import Column, Integer, String, ForeignKey, Table
from sqlalchemy.orm import relationship
from data.database import Base, SessionFactory


user_roles = Table(
    "user_roles",
    Base.metadata,
    Column("user_id", Integer, ForeignKey("users.id"), primary_key=True),
    Column("role_id", Integer, ForeignKey("roles.id"), primary_key=True),
)


class RoleTable(Base):
    __tablename__ = "roles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(32), nullable=False, unique=True)
    label = Column(String(64), nullable=False)

    users = relationship("UserTable", secondary=user_roles, back_populates="roles")

    def to_dict(self):
        return {"id": self.id, "name": self.name, "label": self.label}


class RoleModel:
    def get_all(self):
        with SessionFactory() as session:
            roles = session.query(RoleTable).all()
            return [r.to_dict() for r in roles]

    def get_by_name(self, name):
        with SessionFactory() as session:
            role = session.query(RoleTable).filter_by(name=name).first()
            return role

    def get_by_names(self, names):
        if not names:
            return []
        with SessionFactory() as session:
            return session.query(RoleTable).filter(RoleTable.name.in_(names)).all()

    def create(self, name, label):
        with SessionFactory() as session:
            role = RoleTable(name=name, label=label)
            session.add(role)
            session.commit()
            session.refresh(role)
            return role.to_dict()


role_model = RoleModel()
