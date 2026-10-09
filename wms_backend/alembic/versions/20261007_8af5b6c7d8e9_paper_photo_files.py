"""Move private paper photographs to verified persistent files.

Revision ID: 8af5b6c7d8e9
Revises: 79e4f5a6b7c8
"""
from types import SimpleNamespace

from alembic import op
import sqlalchemy as sa

from services import paper_photo_storage as storage
from services import paper_photo_transfer as transfer

revision = "8af5b6c7d8e9"
down_revision = "79e4f5a6b7c8"
branch_labels = None
depends_on = None


def _online():
    if op.get_context().as_sql:
        raise RuntimeError("Photo migration requires an online database and its persistent photo volume")
    return op.get_bind()


def _columns(connection):
    return {column["name"]: column for column in sa.inspect(connection).get_columns("paper_intake_photos")}


def _photos(connection):
    return sa.Table("paper_intake_photos", sa.MetaData(), autoload_with=connection)


def _rows(connection, table, fields):
    # Keyset iteration bounds memory to a single photograph and permits retries.
    previous = None
    while True:
        query = sa.select(*(table.c[name] for name in fields)).order_by(table.c.uid).limit(1)
        if previous is not None:
            query = query.where(table.c.uid > previous)
        row = connection.execute(query).mappings().first()
        if row is None:
            break
        previous = row["uid"]
        yield row


def upgrade():
    connection = _online()
    columns = _columns(connection)
    table = _photos(connection)
    photo_count = connection.execute(sa.select(sa.func.count()).select_from(table)).scalar()
    if "data" in columns and photo_count:
        # Export is a separate, read-only operation. Refuse schema changes if
        # its manifest does not describe every current source byte and file.
        transfer.validate_manifest(connection, verify_blobs=True)
    # MySQL DDL commits independently. Reinspect and tolerate a previous failed
    # run; never discard the source BLOB before every target file is verified.
    for name, column_type in (("storage_path", sa.String(512)), ("size_bytes", sa.BigInteger()), ("sha256", sa.String(64))):
        if name not in columns:
            op.add_column("paper_intake_photos", sa.Column(name, column_type, nullable=True))
    if not sa.inspect(connection).has_table("paper_photo_cleanup"):
        op.create_table("paper_photo_cleanup",
            sa.Column("storage_path", sa.String(512), primary_key=True),
            sa.Column("size_bytes", sa.BigInteger(), nullable=False),
            sa.Column("packing_list_uid", sa.String(32)),
            sa.Column("created_at", sa.String(32), nullable=False))
    cleanup_indexes = {item["name"] for item in sa.inspect(connection).get_indexes("paper_photo_cleanup")}
    if "ix_paper_photo_cleanup_packing_list_uid" not in cleanup_indexes:
        op.create_index("ix_paper_photo_cleanup_packing_list_uid", "paper_photo_cleanup", ["packing_list_uid"])
    table = _photos(connection)
    missing_metadata = connection.execute(sa.select(sa.func.count()).select_from(table).where(sa.or_(
        table.c.storage_path.is_(None), table.c.size_bytes.is_(None), table.c.sha256.is_(None),
    ))).scalar()
    if "data" not in table.c:
        if missing_metadata:
            # A retry after MySQL committed DROP COLUMN still needs the saved
            # manifest. Metadata is intentionally imported by the second CLI.
            transfer.validate_manifest(connection)
        else:
            for row in _rows(connection, table, ("uid", "storage_path", "size_bytes", "sha256")):
                storage.read_bytes(SimpleNamespace(**row))
    existing_unique = {item["name"] for item in sa.inspect(connection).get_unique_constraints("paper_intake_photos")}
    columns = _columns(connection)
    with op.batch_alter_table("paper_intake_photos") as batch:
        for name, column_type in (("storage_path", sa.String(512)), ("size_bytes", sa.BigInteger()), ("sha256", sa.String(64))):
            if columns[name]["nullable"] and not missing_metadata:
                batch.alter_column(name, existing_type=column_type, nullable=False)
        if "uq_paper_intake_photo_storage_path" not in existing_unique:
            batch.create_unique_constraint("uq_paper_intake_photo_storage_path", ["storage_path"])
        if "data" in columns:
            batch.drop_column("data")


def downgrade():
    connection = _online()
    if sa.inspect(connection).has_table("paper_photo_cleanup"):
        cleanup = sa.Table("paper_photo_cleanup", sa.MetaData(), autoload_with=connection)
        if connection.execute(sa.select(sa.func.count()).select_from(cleanup)).scalar():
            raise RuntimeError("Retry outstanding photo cleanup before downgrading")
    table = _photos(connection)
    # A rollback restores only currently retained photos. Deliberately deleted
    # photographs remain deleted; their bytes are never reconstructed.
    metadata_columns = {"storage_path", "size_bytes", "sha256"}
    if metadata_columns.issubset(table.c.keys()):
        missing_metadata = connection.execute(sa.select(sa.func.count()).select_from(table).where(sa.or_(
            table.c.storage_path.is_(None), table.c.size_bytes.is_(None), table.c.sha256.is_(None),
        ))).scalar()
        exported = {row["uid"]: row for row in transfer.validate_manifest(connection)} if missing_metadata else {}

        def restored_metadata(row):
            if row["uid"] not in exported:
                return row
            original = exported[row["uid"]]
            for name in metadata_columns:
                if row[name] is not None and row[name] != original[name]:
                    raise RuntimeError("Stored photo metadata conflicts with the saved export")
            return original

        for row in _rows(connection, table, ("uid", "storage_path", "size_bytes", "sha256")):
            storage.read_bytes(SimpleNamespace(**restored_metadata(row)))
        if "data" not in table.c:
            op.add_column("paper_intake_photos", sa.Column("data", sa.LargeBinary(length=16777216), nullable=True))
            table = _photos(connection)
        for row in _rows(connection, table, ("uid", "storage_path", "size_bytes", "sha256")):
            connection.execute(table.update().where(table.c.uid == row["uid"]).values(data=storage.read_bytes(SimpleNamespace(**restored_metadata(row)))))
    else:
        # A previous MySQL attempt can have committed some DROP COLUMNs. It
        # only starts dropping metadata after all BLOBs have been restored.
        if "data" not in table.c:
            raise RuntimeError("Incomplete photo rollback metadata; restore from the verified backup")
        if connection.execute(sa.select(sa.func.count()).select_from(table).where(table.c.data.is_(None))).scalar():
            raise RuntimeError("Incomplete photo BLOB restoration; retained metadata is required")
    columns = _columns(connection)
    existing_unique = {item["name"] for item in sa.inspect(connection).get_unique_constraints("paper_intake_photos")}
    with op.batch_alter_table("paper_intake_photos") as batch:
        if columns["data"]["nullable"]:
            batch.alter_column("data", existing_type=sa.LargeBinary(length=16777216), nullable=False)
        if "uq_paper_intake_photo_storage_path" in existing_unique:
            batch.drop_constraint("uq_paper_intake_photo_storage_path", type_="unique")
        for name in metadata_columns:
            if name in columns:
                batch.drop_column(name)
    if sa.inspect(connection).has_table("paper_photo_cleanup"):
        op.drop_table("paper_photo_cleanup")
