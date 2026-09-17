"""ocr_text, ocr_word, extracted_field, and processing_job execution columns

Three constraints here are the slice's actual invariants, expressed where they cannot
be bypassed by a direct write:

  CHECK (source = 'human' OR source_span_start IS NOT NULL)
      Invariant 7 as resolved by docs/adr/0011. A machine field with no span is
      rejected; a human field is permitted none, because a person typing what the OCR
      could not read has nothing to point at.

  CHECK (status = 'draft' OR verified_by IS NOT NULL)
      Invariant 9: AI output is always draft, and only an explicit human commit
      transitions a field to verified. No pipeline stage can write `verified`,
      because doing so without naming a human violates the constraint.

  CHECK (source = 'human') = (entered_by IS NOT NULL)
      A human field names the person. Accountability is what replaces traceability
      when there is no span to trace.

`ocr_word` is the char-offset-to-bbox map. Slice 5b highlights a field's source span
in the scan; slice 7 needs coordinates to redact. Both need to turn character offsets
into rectangles, and that mapping is produced once, here, rather than re-derived.

Storing OCR text is not logging it. Invariant 12 forbids writing document content to
logs; the text has to live somewhere to be the retrieval path.

Revision ID: 0006_pipeline
Revises: 0005_integrity
Create Date: 2026-09-18
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006_pipeline"
down_revision: Union[str, None] = "0005_integrity"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

APP_ROLE = "ordin_app"


def upgrade() -> None:
    # --- OCR output -----------------------------------------------------------
    op.create_table(
        "ocr_text",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("version_id", sa.Uuid(), sa.ForeignKey("document_version.id"),
                  nullable=False, unique=True),
        sa.Column("text", sa.Text(), nullable=False),
        # Declared honestly: `embedded_text_layer` is NOT ocr and slice 11a must
        # exclude it from character error rate (docs/adr/0012).
        sa.Column("method", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("maturity", sa.Text(), nullable=False, server_default="mvp"),
        sa.Column("mean_confidence", sa.Float(), nullable=True),
        sa.Column("requires_manual_entry", sa.Boolean(), nullable=False,
                  server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.CheckConstraint(
            "method IN ('tesseract_ocr','embedded_text_layer')", name="ck_ocr_method"
        ),
    )

    op.create_table(
        "ocr_word",
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), primary_key=True),
        sa.Column("version_id", sa.Uuid(), sa.ForeignKey("document_version.id"),
                  nullable=False),
        sa.Column("page_no", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("char_start", sa.Integer(), nullable=False),
        sa.Column("char_end", sa.Integer(), nullable=False),
        sa.Column("x0", sa.Float(), nullable=False),
        sa.Column("y0", sa.Float(), nullable=False),
        sa.Column("x1", sa.Float(), nullable=False),
        sa.Column("y1", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.CheckConstraint("char_end > char_start", name="ck_ocr_word_span"),
    )
    op.create_index("ix_ocr_word_span", "ocr_word", ["version_id", "char_start", "char_end"])

    # --- extracted fields -----------------------------------------------------
    op.create_table(
        "extracted_field",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("version_id", sa.Uuid(), sa.ForeignKey("document_version.id"),
                  nullable=False),
        sa.Column("case_id", sa.Uuid(), sa.ForeignKey("case_record.id"), nullable=False),
        sa.Column("field_key", sa.Text(), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        # Invariant 7's provenance tuple.
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("source_span_start", sa.Integer(), nullable=True),
        sa.Column("source_span_end", sa.Integer(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("provider", sa.Text(), nullable=True),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("prompt_version", sa.Text(), nullable=True),
        # Invariant 9.
        sa.Column("status", sa.Text(), nullable=False, server_default="draft"),
        sa.Column("verified_by", sa.Uuid(), sa.ForeignKey("app_user.id"), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        # ADR 0011: accountability where there is no span.
        sa.Column("entered_by", sa.Uuid(), sa.ForeignKey("app_user.id"), nullable=True),
        sa.Column("entered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.UniqueConstraint("version_id", "field_key", "source", name="uq_field_per_source"),
        sa.CheckConstraint(
            "source IN ('regex','ner','llm','human')", name="ck_field_source"
        ),
        sa.CheckConstraint("status IN ('draft','verified')", name="ck_field_status"),
        # ADR 0011. The half of invariant 7 that protects something: no machine may
        # assert a value it cannot point at.
        sa.CheckConstraint(
            "source = 'human' OR source_span_start IS NOT NULL",
            name="ck_machine_field_has_span",
        ),
        sa.CheckConstraint(
            "source_span_end IS NULL OR source_span_end > source_span_start",
            name="ck_field_span_ordered",
        ),
        # Invariant 9: nothing reaches `verified` without naming the human who did it.
        sa.CheckConstraint(
            "status = 'draft' OR verified_by IS NOT NULL", name="ck_verified_names_a_human"
        ),
        # A human field names its author.
        sa.CheckConstraint(
            "(source = 'human') = (entered_by IS NOT NULL)", name="ck_human_field_has_author"
        ),
    )
    op.create_index("ix_extracted_field_version", "extracted_field", ["version_id"])

    # --- job execution record -------------------------------------------------
    # The reliability invariant: every stage records status, provider, maturity,
    # timestamps, errors, retry count, input version and output reference.
    op.add_column("processing_job", sa.Column("started_at", sa.DateTime(timezone=True)))
    op.add_column("processing_job", sa.Column("finished_at", sa.DateTime(timezone=True)))
    op.add_column("processing_job", sa.Column("output_ref", sa.Text()))

    for table in ("ocr_text", "ocr_word", "extracted_field"):
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO {APP_ROLE}")
    op.execute(f"GRANT USAGE, SELECT ON SEQUENCE ocr_word_id_seq TO {APP_ROLE}")


def downgrade() -> None:
    op.drop_column("processing_job", "output_ref")
    op.drop_column("processing_job", "finished_at")
    op.drop_column("processing_job", "started_at")
    op.drop_table("extracted_field")
    op.drop_table("ocr_word")
    op.drop_table("ocr_text")
