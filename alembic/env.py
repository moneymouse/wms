"""Alembic environment configuration.

This module configures Alembic to work with the WMS SQLAlchemy models.
"""

import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Add project root to path so we can import our models
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import all models to register them with Base.metadata
from data.database import Base
from data.DB import OrderTable, CargoTable  # noqa: F401
from data.user.User import UserTable  # noqa: F401
from data.user.Role import RoleTable  # noqa: F401
from data.user.PasswordResetRequest import PasswordResetRequestTable
from data.customer.Customer import CustomerTable, ReceiverTable  # noqa: F401
from data.packing.PackingList import (  # noqa: F401
    PackingListTable,
    BoxTable,
    BoxWorkerTable,
)
from data.finance.BonusRate import BonusRateTable  # noqa: F401
from data.finance.BonusItem import BonusItemTable  # noqa: F401
from data.DB import CustomsCodeTable, GoodsNameTable, ExcelTemplateTable  # noqa: F401

# this is the Alembic Config object
config = context.config

# Interpret the config file for Python logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Set target metadata for autogenerate support
target_metadata = Base.metadata


def get_url():
    """Get database URL from environment or config file."""
    return os.environ.get(
        "DATABASE_URL",
        config.get_main_option("sqlalchemy.url"),
    )


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL and not an Engine.
    Calls to context.execute() here emit the given string to the script output.
    """
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine and associate a connection
    with the context.
    """
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = get_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
