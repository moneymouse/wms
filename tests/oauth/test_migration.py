"""Exercise the checked-in OAuth migration against an isolated database."""

import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect

from data.oauth import OAuthAuthorizationCodeTable, OAuthClientTable, OAuthTokenFamilyTable, OAuthTokenTable


def test_oauth_migration_upgrade_matches_models_and_downgrade_removes_only_oauth():
    path = Path(__file__).resolve().parents[2] / "alembic/versions/20261005_g27d8e9f0a1b_mcp_oauth.py"
    spec = importlib.util.spec_from_file_location("oauth_migration_under_test", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE users (id INTEGER PRIMARY KEY)")
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
        inspector = inspect(connection)
        for model in (OAuthClientTable, OAuthAuthorizationCodeTable, OAuthTokenFamilyTable, OAuthTokenTable):
            assert {column["name"] for column in inspector.get_columns(model.__tablename__)} == set(model.__table__.columns.keys())
        assert inspector.get_foreign_keys("oauth_token_families")[0]["options"]["ondelete"] == "CASCADE"
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
        assert inspect(connection).get_table_names() == ["users"]
    engine.dispose()
