import os

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()


def get_database_url() -> str:
    return os.environ.get(
        "DATABASE_URL",
        "mysql+pymysql://wms_user:wms_password@localhost:3306/wms_db?charset=utf8mb4",
    )


engine = create_engine(
    get_database_url(),
    pool_pre_ping=True,
    pool_recycle=3600,
    echo=False,
)

SessionFactory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
