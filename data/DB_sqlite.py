import time
import random
from typing import Any, Dict, List, Optional
from sqlalchemy import create_engine, Column, String, Integer, Float, Boolean, DateTime, Text, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship, Session, Mapped
from sqlalchemy.sql import func
import json
from pathlib import Path

Base = declarative_base()

# SQLite数据库文件路径
DB_PATH = "./data/data/wms_database.db"

class OrderTable(Base):
    __tablename__ = 'orders'

    uid = Column(String, primary_key=True)
    order_id = Column(String, unique=True)
    customer_name = Column(String)
    transportation = Column(String)
    receiver = Column(String)
    receiver_phone = Column(String)
    mail = Column(String)
    country = Column(String)
    province = Column(String)
    city = Column(String)
    address = Column(Text)
    en_name = Column(String)
    cn_name = Column(String)
    total_weight = Column(Float)
    cargo_count = Column(Integer, default=0)
    archive = Column(Boolean, default=False)
    post_code = Column(String)
    zip_code = Column(String)
    order_date = Column(String)
    tag_all = Column(String)
    create_date = Column(String)
    update_date = Column(String)

    # 关系
    cargos: Mapped['CargoTable'] = relationship(back_populates="order")

class CargoTable(Base):
    __tablename__ = 'cargos'

    uid = Column(String, primary_key=True)
    origin_id = Column(String)
    transfer_id = Column(String, default="")
    tag = Column(String, default="init")
    count = Column(Integer, default=0)
    weight = Column(Float, default=0.0)
    real_en_name = Column(String)
    price = Column(Float)
    status = Column(Integer, default=0)
    archive = Column(Boolean, default=False)
    date = Column(String)
    waybill_id = Column(String, default="")
    target_order_uid = Column(String, ForeignKey('orders.uid'))
    create_date = Column(String)
    update_date = Column(String)

    # 关系
    order: Mapped[List['OrderTable']] = relationship(back_populates="cargos")

class SQLiteModel:
    def __init__(self, table_class, db_session: Session):
        self.table_class = table_class
        self.session = db_session

    def create(self, record: dict) -> str:
        # 生成唯一ID
        uid = str(int(time.time() * 1000000)) + str(random.randint(10, 99))

        # 创建记录
        create_time = time.strftime("%Y-%m-%d %H:%M")
        record_data = record.copy()
        record_data['uid'] = uid
        record_data['create_date'] = create_time
        record_data['archive'] = False

        # 创建数据库记录
        db_record = self.table_class(**record_data)
        self.session.add(db_record)
        self.session.commit()

        return uid

    def read(self, uid: Optional[str] = None, _fields: List[str] = None, except_fields: List[str] = None) -> Any:
        query = self.session.query(self.table_class).filter(self.table_class.archive == False)

        if uid is not None:
            # 查询单个记录
            record = query.filter(self.table_class.uid == uid).first()
            if not record:
                return None
            return self._record_to_dict(record, _fields, except_fields)
        else:
            # 查询所有记录
            records = query.all()
            return [self._record_to_dict(record, _fields, except_fields) for record in records]

    def update(self, uid: str, record: dict):
        db_record = self.session.query(self.table_class).filter(
            self.table_class.uid == uid,
            self.table_class.archive == False
        ).first()

        if db_record:
            # 更新字段
            for key, value in record.items():
                if hasattr(db_record, key):
                    setattr(db_record, key, value)

            # 更新修改时间
            db_record.update_date = time.strftime("%Y-%m-%d %H:%M")
            self.session.commit()

    def archive(self, uid: str):
        db_record = self.session.query(self.table_class).filter(
            self.table_class.uid == uid
        ).first()

        if db_record:
            db_record.archive = True
            self.session.commit()

    def delete(self, uid: str):
        db_record = self.session.query(self.table_class).filter(
            self.table_class.uid == uid
        ).first()

        if db_record:
            self.session.delete(db_record)
            self.session.commit()

    def _record_to_dict(self, record, _fields: List[str] = None, except_fields: List[str] = None) -> dict:
        """将SQLAlchemy记录转换为字典"""
        result = {}

        # 获取所有列
        columns = [column.name for column in record.__table__.columns]

        for column in columns:
            if except_fields and column in except_fields:
                continue
            if _fields and column not in _fields:
                continue
            result[column] = getattr(record, column)

        # 处理关系字段
        if hasattr(record, 'cargos') and record.cargos is not None:
            # 对于订单，添加cargo_uid_list
            result['cargo_uid_list'] = [cargo.uid for cargo in record.cargos if not cargo.archive]

        return result

class SQLiteOrderModel(SQLiteModel):
    def create(self, record: dict) -> str:
        # 为订单创建添加特殊逻辑
        if 'cargo_uid_list' in record:
            del record['cargo_uid_list']  # 这个字段通过关系处理
        return super().create(record)

class SQLiteCargoModel(SQLiteModel):
    def create(self, record: dict) -> str:
        return super().create(record)

class DatabaseManager:
    def __init__(self, db_path: str = DB_PATH):
        self.engine = create_engine(f'sqlite:///{db_path}', echo=False)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        self.create_tables()

    def create_tables(self):
        """创建所有表"""
        Base.metadata.create_all(bind=self.engine)

    def get_session(self) -> Session:
        """获取数据库会话"""
        return self.SessionLocal()

    def close_session(self, session: Session):
        """关闭数据库会话"""
        session.close()

# 全局数据库管理器和模型实例
db_manager = DatabaseManager()
session = db_manager.get_session()

# 创建模型实例
sqlite_order_model = SQLiteOrderModel(OrderTable, session)
sqlite_cargo_model = SQLiteCargoModel(CargoTable, session)

def migrate_from_pickle():
    """从pickle文件迁移数据到SQLite"""
    from .DB import data_point_of

    print("开始数据迁移...")

    # 迁移订单数据
    try:
        order_data = data_point_of('order')
        print(f"找到 {len(order_data)} 条订单记录")

        for uid, order_record in order_data.items():
            try:
                # 准备订单数据
                order_dict = order_record.copy()
                if 'cargo_uid_list' in order_dict:
                    del order_dict['cargo_uid_list']  # 通过关系处理

                # 创建订单记录
                new_order = OrderTable(**order_dict)
                session.add(new_order)

            except Exception as e:
                print(f"迁移订单 {uid} 时出错: {e}")
                continue

        session.commit()
        print("订单数据迁移完成")

    except Exception as e:
        print(f"迁移订单数据时出错: {e}")
        session.rollback()

    # 迁移货物数据
    try:
        cargo_data = data_point_of('cargo')
        print(f"找到 {len(cargo_data)} 条货物记录")

        for uid, cargo_record in cargo_data.items():
            try:
                # 创建货物记录
                new_cargo = CargoTable(**cargo_record)
                session.add(new_cargo)

            except Exception as e:
                print(f"迁移货物 {uid} 时出错: {e}")
                continue

        session.commit()
        print("货物数据迁移完成")

    except Exception as e:
        print(f"迁移货物数据时出错: {e}")
        session.rollback()

    print("数据迁移完成!")

if __name__ == "__main__":
    # 运行迁移
    migrate_from_pickle()


