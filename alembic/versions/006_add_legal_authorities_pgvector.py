"""Add legal authorities tables with pgvector

Revision ID: 006
Revises: 005
Create Date: 2025-01-17

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

# revision identifiers
revision = '006'
down_revision = '005_add_organizations_billing'
branch_labels = None
depends_on = None


def table_exists(conn, table_name):
    """Check if a table exists in the database."""
    result = conn.execute(text(f"""
        SELECT EXISTS(
            SELECT 1 FROM information_schema.tables WHERE table_name = '{table_name}'
        )
    """))
    return result.scalar()


def upgrade() -> None:
    conn = op.get_bind()

    # Check if pgvector extension is available
    result = conn.execute(text("""
        SELECT EXISTS(
            SELECT 1 FROM pg_available_extensions WHERE name = 'vector'
        )
    """))
    pgvector_available = result.scalar()

    if pgvector_available:
        # Enable pgvector extension
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # Create legal_authorities table if it doesn't exist
    if not table_exists(conn, 'legal_authorities'):
        op.create_table(
            'legal_authorities',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('matter_id', sa.Integer(), nullable=False),
            sa.Column('clio_document_id', sa.String(128), nullable=True),
            sa.Column('clio_folder_id', sa.String(128), nullable=True),
            sa.Column('filename', sa.String(512), nullable=False),
            sa.Column('content_hash', sa.String(64), nullable=True),
            sa.Column('total_chunks', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('is_processed', sa.Boolean(), nullable=False, server_default='false'),
            sa.Column('processing_error', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(['matter_id'], ['matters.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index('ix_legal_authorities_id', 'legal_authorities', ['id'])
        op.create_index('ix_legal_authorities_clio_document_id', 'legal_authorities', ['clio_document_id'])
        op.create_index('ix_legal_authorities_matter_id', 'legal_authorities', ['matter_id'])

    # Create legal_authority_chunks table if it doesn't exist
    if not table_exists(conn, 'legal_authority_chunks'):
        op.create_table(
            'legal_authority_chunks',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('legal_authority_id', sa.Integer(), nullable=False),
            sa.Column('chunk_index', sa.Integer(), nullable=False),
            sa.Column('chunk_text', sa.Text(), nullable=False),
            sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(['legal_authority_id'], ['legal_authorities.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index('ix_legal_authority_chunks_id', 'legal_authority_chunks', ['id'])
        op.create_index('ix_legal_authority_chunks_legal_authority_id', 'legal_authority_chunks', ['legal_authority_id'])

    if pgvector_available:
        # Check if embedding column already exists
        result = conn.execute(text("""
            SELECT EXISTS(
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'legal_authority_chunks' AND column_name = 'embedding'
            )
        """))
        embedding_exists = result.scalar()

        if not embedding_exists:
            # Add vector column for embeddings (1536 dimensions for Amazon Titan)
            op.execute("ALTER TABLE legal_authority_chunks ADD COLUMN embedding vector(1536)")

            # Create IVFFlat index for fast similarity search
            # Using cosine similarity (vector_cosine_ops)
            op.execute("""
                CREATE INDEX IF NOT EXISTS ix_legal_authority_chunks_embedding
                ON legal_authority_chunks
                USING ivfflat (embedding vector_cosine_ops)
                WITH (lists = 100)
            """)


def downgrade() -> None:
    op.drop_table('legal_authority_chunks')
    op.drop_table('legal_authorities')
    # Note: We don't drop the vector extension as other things may use it
