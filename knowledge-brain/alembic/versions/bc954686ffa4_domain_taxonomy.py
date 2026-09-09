"""domain taxonomy

Revision ID: bc954686ffa4
Revises: d07b96877e35
Create Date: 2026-09-09 16:46:44.968583

"""
import uuid
from datetime import UTC, datetime
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'bc954686ffa4'
down_revision: Union[str, Sequence[str], None] = 'd07b96877e35'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Replace the free-text documents.domains array with a real,
    admin-managed per-tenant taxonomy (a domains table plus a
    document_domains join table), fixing the vocabulary-drift problem
    where "HR" and "Human Resources" were two unrelated tags with
    nothing to notice or fix that.

    Backfills every existing domain string into a real Domain row before
    dropping the old column, so no existing tagging is lost — this also
    folds in the cheap half of the fix for free: names are trimmed and
    compared case-insensitively during backfill, so "HR", "hr", and
    " HR " collapse into one real domain instead of three, using
    whichever casing was seen first as the canonical display name.
    """
    op.create_table(
        "domains",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    # Case-insensitive: a plain UniqueConstraint on (tenant_id, name) would
    # let "HR" and "hr" both insert for the same tenant, undoing the very
    # vocabulary-drift fix this migration exists for.
    op.create_index(
        "uq_domain_tenant_name_ci",
        "domains",
        ["tenant_id", sa.text("lower(name)")],
        unique=True,
    )
    op.create_table(
        "document_domains",
        sa.Column("document_id", sa.UUID(), nullable=False),
        sa.Column("domain_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["domain_id"], ["domains.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("document_id", "domain_id"),
    )

    # --- Backfill: normalize every existing free-text domain into a real row ---
    connection = op.get_bind()

    documents_table = sa.table(
        "documents",
        sa.column("id", sa.UUID()),
        sa.column("tenant_id", sa.UUID()),
        sa.column("domains", sa.ARRAY(sa.String())),
    )
    domains_table = sa.table(
        "domains",
        sa.column("id", sa.UUID()),
        sa.column("tenant_id", sa.UUID()),
        sa.column("name", sa.String()),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    document_domains_table = sa.table(
        "document_domains",
        sa.column("document_id", sa.UUID()),
        sa.column("domain_id", sa.UUID()),
    )

    rows = connection.execute(
        sa.select(documents_table.c.id, documents_table.c.tenant_id, documents_table.c.domains)
    ).fetchall()

    # (tenant_id, casefolded name) -> the real domain_id already created for
    # it — first-seen casing becomes the canonical display name, matching
    # how a person reading two near-duplicate tags would naturally resolve
    # them, absent a human deliberately picking one (that's what renaming
    # in the admin panel is for, afterward).
    domain_cache: dict[tuple, uuid.UUID] = {}
    for doc_id, tenant_id, raw_domains in rows:
        # A document's own raw list can itself contain near-duplicates
        # ("hr" and " HR ") that normalize to the very same domain — this
        # tracks which domain_ids this one document has already been
        # linked to, so a real duplicate (document_id, domain_id) row is
        # never attempted twice against the join table's primary key.
        linked_domain_ids: set = set()
        for raw_name in raw_domains or []:
            name = raw_name.strip()
            if not name:
                continue
            key = (tenant_id, name.casefold())
            domain_id = domain_cache.get(key)
            if domain_id is None:
                domain_id = uuid.uuid4()
                domain_cache[key] = domain_id
                connection.execute(
                    domains_table.insert().values(
                        id=domain_id,
                        tenant_id=tenant_id,
                        name=name,
                        created_at=datetime.now(UTC),
                    )
                )
            if domain_id in linked_domain_ids:
                continue
            linked_domain_ids.add(domain_id)
            connection.execute(
                document_domains_table.insert().values(document_id=doc_id, domain_id=domain_id)
            )

    op.drop_column("documents", "domains")


def downgrade() -> None:
    """Reverses the schema, not the backfill's normalization — a document
    tagged "HR" and "hr" separately before this migration comes back
    tagged with whichever single canonical name backfill chose, not both
    original strings. Restoring the exact pre-migration strings would need
    a second backfill pass in reverse, not attempted here since downgrading
    a production data migration is already a rare, deliberate action, not
    a routine one this needs to make painless.
    """
    op.add_column(
        "documents",
        sa.Column("domains", sa.ARRAY(sa.String()), nullable=False, server_default="{}"),
    )

    connection = op.get_bind()
    documents_table = sa.table(
        "documents",
        sa.column("id", sa.UUID()),
        sa.column("domains", sa.ARRAY(sa.String())),
    )
    domains_table = sa.table(
        "domains",
        sa.column("id", sa.UUID()),
        sa.column("name", sa.String()),
    )
    document_domains_table = sa.table(
        "document_domains",
        sa.column("document_id", sa.UUID()),
        sa.column("domain_id", sa.UUID()),
    )

    rows = connection.execute(
        sa.select(
            document_domains_table.c.document_id, domains_table.c.name
        ).select_from(
            document_domains_table.join(
                domains_table, domains_table.c.id == document_domains_table.c.domain_id
            )
        )
    ).fetchall()

    names_by_document: dict[uuid.UUID, list[str]] = {}
    for document_id, name in rows:
        names_by_document.setdefault(document_id, []).append(name)

    for document_id, names in names_by_document.items():
        connection.execute(
            documents_table.update()
            .where(documents_table.c.id == document_id)
            .values(domains=names)
        )

    op.drop_table("document_domains")
    op.drop_table("domains")
