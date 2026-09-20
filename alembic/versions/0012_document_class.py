"""A document knows what kind of document it is.

Revision ID: 0012_document_class
Revises: 0011_reference_trigram

Two gaps close with one column.

**The Unified Case Vault could not say what anything was.** `document` carried a
free-text `title`, so nothing in the schema distinguished an FIR from a forensic report.
A vault that cannot tell you what it holds is a folder.

**The completeness engine had nothing to count.** "Flags missing documents before a
charge sheet is filed" requires knowing which documents are present, which requires a
class. It was cut for exactly this reason and stayed cut.

`other` is the default and is not a failure state: a case file contains correspondence,
receipts and notes that belong to no checklist. What matters is that a document can be
*told* it is an FIR, and that the answer is a column rather than a guess about its title.

The check constraint is in the database rather than only in the enum, because a value
the application never writes can still arrive from a migration, a fixture loader or a
hand-typed UPDATE — and a completeness check that silently ignores an unrecognised
class would report a case complete because it could not read one of its documents.
"""
import sqlalchemy as sa
from alembic import op

revision: str = "0012_document_class"
down_revision: str = "0011_reference_trigram"
branch_labels = None
depends_on = None

CLASSES = ("fir", "statement", "forensic_report", "charge_sheet", "court_order", "other")


def upgrade() -> None:
    op.add_column(
        "document",
        sa.Column("doc_class", sa.Text(), nullable=False, server_default="other"),
    )
    values = ", ".join(f"'{c}'" for c in CLASSES)
    op.create_check_constraint(
        "ck_document_class", "document", f"doc_class IN ({values})"
    )
    # Completeness counts documents per class within a case, which is the only query
    # this column serves.
    op.create_index("ix_document_case_class", "document", ["case_id", "doc_class"])


def downgrade() -> None:
    op.drop_index("ix_document_case_class", table_name="document")
    op.drop_constraint("ck_document_class", "document", type_="check")
    op.drop_column("document", "doc_class")
