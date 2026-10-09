"""OAuth clients, authorization codes and rotating token families for MCP."""

from alembic import op
import sqlalchemy as sa

revision = "g27d8e9f0a1b"
down_revision = "027d8e9f0a1b"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("oauth_clients",
        sa.Column("client_key", sa.String(64), primary_key=True),
        sa.Column("client_id", sa.Text(), nullable=False),
        sa.Column("secret_hash", sa.String(64)),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("issued_at", sa.BigInteger(), nullable=False),
        sa.Column("metadata_expires_at", sa.BigInteger()))
    op.create_table("oauth_authorization_codes",
        sa.Column("code_hash", sa.String(64), primary_key=True),
        sa.Column("client_key", sa.String(64), sa.ForeignKey("oauth_clients.client_key", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("redirect_uri", sa.Text(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("code_challenge", sa.String(128), nullable=False),
        sa.Column("code_challenge_method", sa.String(16), nullable=False),
        sa.Column("resource", sa.Text(), nullable=False),
        sa.Column("issuer", sa.Text(), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("expires_at", sa.BigInteger(), nullable=False),
        sa.Column("consumed_at", sa.BigInteger()),
        sa.Column("family_id", sa.String(64)))
    op.create_table("oauth_token_families",
        sa.Column("family_id", sa.String(64), primary_key=True),
        sa.Column("client_key", sa.String(64), sa.ForeignKey("oauth_clients.client_key", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("resource", sa.Text(), nullable=False),
        sa.Column("issuer", sa.Text(), nullable=False),
        sa.Column("created_at", sa.BigInteger(), nullable=False),
        sa.Column("expires_at", sa.BigInteger(), nullable=False),
        sa.Column("revoked_at", sa.BigInteger()))
    op.create_table("oauth_tokens",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("access_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("refresh_hash", sa.String(64), unique=True),
        sa.Column("family_id", sa.String(64), sa.ForeignKey("oauth_token_families.family_id", ondelete="CASCADE"), nullable=False),
        sa.Column("client_key", sa.String(64), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("issued_at", sa.BigInteger(), nullable=False),
        sa.Column("expires_at", sa.BigInteger(), nullable=False),
        sa.Column("refresh_expires_at", sa.BigInteger(), nullable=False),
        sa.Column("consumed_at", sa.BigInteger()),
        sa.Column("revoked_at", sa.BigInteger()))
    op.create_index("ix_oauth_tokens_family_id", "oauth_tokens", ["family_id"])


def downgrade():
    op.drop_index("ix_oauth_tokens_family_id", table_name="oauth_tokens")
    op.drop_table("oauth_tokens")
    op.drop_table("oauth_token_families")
    op.drop_table("oauth_authorization_codes")
    op.drop_table("oauth_clients")
